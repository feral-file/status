// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title  Feral File Archive Registry
/// @author Feral File
/// @notice On-chain pointer to the Feral File Archive: byte-verified,
///         content-addressed copies of every work Feral File preserves.
///
///         `manifest` holds the IPFS CID of `archive-manifest.json`, which
///         maps each archived collection and series to its content-addressed
///         copy, and names this contract's own address. That back-pointer
///         does one narrow job: a byte-identical clone of this contract
///         cannot point at the authentic manifest, because the manifest
///         names this address, not the clone's. It does not by itself prove
///         which registry is Feral File's — a cloner can close the same
///         loop with a forged manifest. The canonical anchor is
///         institutional: the address published at
///         https://status.feralfile.com and in Feral File's records.
///
///         Contract storage is the permanence mechanism: the full CID
///         history and its timestamps live in state (`historyAt`,
///         `historyTimeAt`), readable forever with plain calls. Event logs
///         are a redundant audit trail, not the recovery path.
///
///         Semantics worth knowing:
///         - `version() == 0` means the manifest has never been set; the
///           empty `manifest` string then means "unset", not "empty".
///         - `transferOwnership(address(0))` cancels a pending transfer.
///         - While the owner (a Gnosis Safe) remains operable, only it can
///           update the manifest. If the owner is ever lost, the contract
///           freezes read-only at the last CID — the intended failure mode
///           for an archive pointer; continuity is institutional, not
///           mechanical. Continuity would be a new registry,
///           announced at the site above.
///         - Assets force-sent to this contract are unrecoverable by design;
///           it holds nothing and recovers nothing.
///
///         The pattern follows the Bitmark blockchain archive (2025):
///         root on Ethereum, data on IPFS.
contract FeralFileArchiveRegistry {
    address public owner;
    address public pendingOwner;

    /// @notice IPFS CID of the current archive-manifest.json ("" until first set).
    string public manifest;

    /// @notice Timestamp of the most recent manifest update (0 until first set).
    uint64 public updatedAt;

    string[] private _history;
    uint64[] private _historyTimes;

    event ManifestUpdated(uint256 indexed version, string cid);
    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    error NotOwner();
    error NotPendingOwner();
    error InvalidCID();
    error TransferPending();
    error NoSuchVersion();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    /// @notice Update the manifest pointer. CIDs must be plain multibase
    ///         alphanumerics (no scheme prefix, no whitespace), 32-256 chars —
    ///         a shape check that rejects "", "ipfs://…", and copy-paste
    ///         artifacts; semantic CID validity is the release tooling's job.
    ///         Reverts while an ownership transfer is pending, so the archive
    ///         cannot change under a handoff the new owner already reviewed
    ///         (cancel the transfer first for an urgent update).
    function setManifest(string calldata cid) external onlyOwner {
        if (pendingOwner != address(0)) revert TransferPending();
        bytes calldata b = bytes(cid);
        if (b.length < 32 || b.length > 256) revert InvalidCID();
        for (uint256 i; i < b.length; ++i) {
            bytes1 c = b[i];
            if (!((c >= 0x30 && c <= 0x39) || (c >= 0x41 && c <= 0x5A) || (c >= 0x61 && c <= 0x7A))) {
                revert InvalidCID();
            }
        }
        manifest = cid;
        _history.push(cid);
        _historyTimes.push(uint64(block.timestamp));
        updatedAt = uint64(block.timestamp);
        emit ManifestUpdated(_history.length, cid);
    }

    /// @notice Number of manifest versions ever set.
    function version() external view returns (uint256) {
        return _history.length;
    }

    /// @notice Manifest CID at index `i` (0 = first ever set).
    function historyAt(uint256 i) external view returns (string memory) {
        if (i >= _history.length) revert NoSuchVersion();
        return _history[i];
    }

    /// @notice Timestamp at which history index `i` became canonical.
    function historyTimeAt(uint256 i) external view returns (uint64) {
        if (i >= _historyTimes.length) revert NoSuchVersion();
        return _historyTimes[i];
    }

    /// @notice Manifest CID by 1-based version number, matching the
    ///         `ManifestUpdated` event's `version` field (which is 1-based,
    ///         while `historyAt` is 0-indexed — this accessor exists so no
    ///         indexer ever has to remember that).
    function historyAtVersion(uint256 v) external view returns (string memory) {
        if (v == 0 || v > _history.length) revert NoSuchVersion();
        return _history[v - 1];
    }

    /// @notice Two-step transfer, so ownership can move to the Feral File
    ///         Safe without risk of a typoed address burning the contract.
    ///         `transferOwnership(address(0))` cancels a pending transfer.
    function transferOwnership(address newOwner) external onlyOwner {
        pendingOwner = newOwner;
        emit OwnershipTransferStarted(owner, newOwner);
    }

    function acceptOwnership() external {
        if (msg.sender != pendingOwner) revert NotPendingOwner();
        emit OwnershipTransferred(owner, msg.sender);
        owner = msg.sender;
        pendingOwner = address(0);
    }
}
