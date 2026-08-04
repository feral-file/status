// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title  Feral File Archive Registry
/// @author Feral File
/// @notice On-chain pointer to the Feral File Archive: byte-verified,
///         content-addressed copies of every work Feral File preserves.
///
///         `manifest` holds the IPFS CID of `archive-manifest.json`, which
///         maps each archived collection and series to its content-addressed
///         copy, and names this contract's own address — resolve the
///         manifest and check that it points back here to authenticate the
///         registry against copies. The canonical address is also published
///         at https://status.feralfile.com.
///
///         The full CID history is kept in contract storage (`historyAt`),
///         not only in event logs, so on-chain readers and post-EIP-4444
///         clients can always reconstruct it.
///
///         Semantics worth knowing:
///         - `version() == 0` means the manifest has never been set; the
///           empty `manifest` string then means "unset", not "empty".
///         - `transferOwnership(address(0))` cancels a pending transfer.
///         - If the owner (a Gnosis Safe) is ever lost, the contract
///           freezes read-only at the last CID — the intended failure mode
///           for an archive pointer. Continuity would be a new registry,
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

    event ManifestUpdated(uint256 indexed version, string cid);
    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    error NotOwner();
    error NotPendingOwner();
    error InvalidCID();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    /// @notice Update the manifest pointer. CIDs must be plain base58/base32
    ///         alphanumerics (no scheme prefix, no whitespace), 46-100 chars —
    ///         rejects "", "ipfs://…", and copy-paste artifacts like trailing
    ///         newlines before they become permanent history.
    function setManifest(string calldata cid) external onlyOwner {
        bytes calldata b = bytes(cid);
        if (b.length < 46 || b.length > 100) revert InvalidCID();
        for (uint256 i; i < b.length; ++i) {
            bytes1 c = b[i];
            if (!((c >= 0x30 && c <= 0x39) || (c >= 0x41 && c <= 0x5A) || (c >= 0x61 && c <= 0x7A))) {
                revert InvalidCID();
            }
        }
        manifest = cid;
        _history.push(cid);
        updatedAt = uint64(block.timestamp);
        emit ManifestUpdated(_history.length, cid);
    }

    /// @notice Number of manifest versions ever set.
    function version() external view returns (uint256) {
        return _history.length;
    }

    /// @notice Manifest CID at index `i` (0 = first ever set).
    function historyAt(uint256 i) external view returns (string memory) {
        return _history[i];
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
