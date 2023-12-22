import json
import random
import time
import sys
import asyncio

from aptos_sdk.account import Account
from aptos1 import RestClient

from loguru import logger
from dotenv import dotenv_values


def get_private_keys():
    with open("private_keys.txt", "r") as f:
        return f.read().splitlines()


class Minter:
    NODE_URL = dotenv_values()["NODE_URL"]
    GAS_LIMIT = dotenv_values()["GAS_LIMIT"]
    GAS_PRICE = dotenv_values()["GAS_PRICE"]

    private_keys = get_private_keys()

    def __init__(self):
        self.rest_client = None

    async def start(self):
        self.rest_client = await RestClient().connect(Minter.NODE_URL)

        accounts = [Account.load_key(private_key) for private_key in Minter.private_keys]

        tasks = []
        for key in Minter.private_keys:
            tasks.append(asyncio.create_task(self.worker(key)))

        await asyncio.gather(*tasks)

        logger.info(f"Loaded {len(accounts)} accounts")

        await self.rest_client.close()

    async def get_map_id(self):
        used_maps = await self.already_minted()

        map_id = random.randint(61020, 126000)
        while str(map_id) in used_maps:
            map_id = random.randint(91020, 126000)
        return map_id

    async def worker(self, key: str):
        account = Account.load_key(key)

        while True:
            sequence = await self.rest_client.account_sequence_number(account.address())

            map_id = await self.get_map_id()
            logger.info(f"Minting map {map_id}")

            payload = {
                "function": "0x3ff12c840442b037a97770807084b7bab31b4b02c06cccbaf9350b1edb2fb450::apt_map::mint_aptmap",
                "type_arguments": [], "arguments": [[(str(map_id))]], "type": "entry_function_payload"}

            await self.mint(account, payload, sequence=sequence)

            await asyncio.sleep(5)
            sequence += 1

    async def already_minted(self):
        import aiohttp

        headers = {
            'authority': 'fullnode.mainnet.aptoslabs.com',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/json',
            'origin': 'https://explorer.aptoslabs.com',
            'referer': 'https://explorer.aptoslabs.com/',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'x-aptos-client': 'aptos-ts-sdk/1.18.0',
        }

        json_data = {
            'function': '0x3ff12c840442b037a97770807084b7bab31b4b02c06cccbaf9350b1edb2fb450::apt_map::get_all_block_minted',
            'type_arguments': [],
            'arguments': [],
        }
        url = 'https://fullnode.mainnet.aptoslabs.com/v1/view'

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=json_data) as response:
                return(await response.json())[0]

    async def mint(self, account: Account, payload: dict, sequence: int = None):
        while True:
            try:
                txn_hash = await self.rest_client.submit_transaction(account, payload, Minter.GAS_LIMIT,
                                                                     Minter.GAS_PRICE, sequence=str(sequence))
                logger.success(f"{str(account.address())[:6]} | Sent transaction {txn_hash} from {account.address()}")
                return True
            except Exception as e:
                if "Transaction already in mempool with a different payload" in str(e):
                    sequence += 1
                    continue
                logger.error(f"{str(account.address())[:6]} | Failed to mint token for {account.address()}: {e}")
                return False


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, colorize=True,
               format="<green>{time:HH:mm:ss.SSS}</green> <blue>{level}</blue> <level>{message}</level>")

    asyncio.run(Minter().start())
