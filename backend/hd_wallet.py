"""HD Wallet (BIP-44) derivation for FozPay clone.

One BIP-39 mnemonic derives unique deposit addresses per index across chains.
EVM chains share the same secp256k1 address (m/44'/60'/0'/0/index).
"""
from bip_utils import (
    Bip39SeedGenerator, Bip39MnemonicGenerator, Bip39WordsNum,
    Bip44, Bip44Coins, Bip44Changes,
)
from eth_account import Account

_EVM = {"ethereum", "polygon", "bsc", "arbitrum"}

_COIN = {
    "tron": Bip44Coins.TRON,
    "bitcoin": Bip44Coins.BITCOIN,
    "litecoin": Bip44Coins.LITECOIN,
    "solana": Bip44Coins.SOLANA,
}

_PATH_COIN = {"ethereum": 60, "polygon": 60, "bsc": 60, "arbitrum": 60,
              "tron": 195, "bitcoin": 0, "litecoin": 2, "solana": 501}


def generate_mnemonic() -> str:
    return str(Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_12))


def seed_from_mnemonic(mnemonic: str, passphrase: str = "") -> bytes:
    return Bip39SeedGenerator(mnemonic).Generate(passphrase)


def derive_address(seed: bytes, chain: str, index: int) -> dict:
    if index < 0:
        raise ValueError("index must be non-negative")
    if chain in _EVM:
        node = (Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
                .Purpose().Coin().Account(0)
                .Change(Bip44Changes.CHAIN_EXT).AddressIndex(index))
        pk = node.PrivateKey().Raw().ToBytes()
        address = Account.from_key(pk).address
        return {"chain": chain, "index": index, "address": address,
                "path": f"m/44'/60'/0'/0/{index}"}
    if chain in _COIN:
        node = (Bip44.FromSeed(seed, _COIN[chain])
                .Purpose().Coin().Account(0)
                .Change(Bip44Changes.CHAIN_EXT).AddressIndex(index))
        return {"chain": chain, "index": index, "address": node.PublicKey().ToAddress(),
                "path": f"m/44'/{_PATH_COIN[chain]}'/0'/0/{index}"}
    raise ValueError(f"unsupported chain: {chain}")


def derive_evm_privkey(seed: bytes, index: int) -> str:
    """Return the private key (hex) that controls the EVM address at this index
    across ALL EVM chains (Ethereum, Polygon, BSC, Arbitrum share the address)."""
    node = (Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT).AddressIndex(index))
    return "0x" + node.PrivateKey().Raw().ToHex()
