// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title  Feral File Archive Registry
/// @author Feral File
/// @notice On-chain pointer to the Feral File Archive: byte-verified,
///         content-addressed copies of every work Feral File preserves.
///
///         `manifest` holds the IPFS CID of `archive-manifest.json`, which
///         maps each archived collection and series to its content-addressed
///         copy. The manifest and every copy it names are on IPFS, so anyone
///         can hold them; this contract makes the mapping itself permanent
///         and publishes it under Feral File's own authority — the same
///         institution that published the works.
///
///         The pattern follows the Bitmark blockchain archive (2025):
///         root on Ethereum, data on IPFS.
///         Human-readable context: https://status.feralfile.com
contract FeralFileArchiveRegistry {
    address public owner;
    address public pendingOwner;

    /// @notice IPFS CID of the current archive-manifest.json.
    string public manifest;

    /// @notice Increments on every manifest update; event history holds all
    ///         prior CIDs.
    uint64 public version;

    event ManifestUpdated(uint64 indexed version, string cid);
    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    error NotOwner();
    error NotPendingOwner();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    function setManifest(string calldata cid) external onlyOwner {
        version += 1;
        manifest = cid;
        emit ManifestUpdated(version, cid);
    }

    /// @notice Two-step transfer, so ownership can move to the Feral File
    ///         Safe without risk of a typoed address burning the contract.
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
