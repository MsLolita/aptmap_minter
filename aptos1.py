import time
import asyncio
from typing import Any, Dict, List, Optional

import aiohttp

U64_MAX = 18446744073709551615


async def wait_to_send_tx(start_time: float, mint_start_time: float, start_earlier_on: float) -> None:
    take_time_to_prepare = time.time() - start_time
    left_to_mint_time = mint_start_time - take_time_to_prepare - time.time() - start_earlier_on
    if left_to_mint_time > 0:
        await asyncio.sleep(left_to_mint_time)


class RestClient:
    """A wrapper around the Aptos-core Rest API"""

    client: aiohttp.ClientSession
    base_url: str

    async def connect(self, base_url: str):
        self.base_url = base_url
        self.client = aiohttp.ClientSession()
        return self

    async def close(self):
        await self.client.close()

    async def account(self, account_address) -> Dict[str, str]:
        """Returns the sequence number and authentication key for an account"""

        response = await self.client.get(f"{self.base_url}/accounts/{account_address}")
        if response.status >= 400:
            raise ApiError(f"{await response.text()} - {account_address}", response.status)
        return await response.json()

    async def account_balance(self, account_address: str) -> int:
        """Returns the test coin balance associated with the account"""
        return (await self.account_resource(
            account_address, "0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>"
        ))["data"]["coin"]["value"]

    async def account_sequence_number(self, account_address) -> int:
        account_res = await self.account(account_address)
        return int(account_res["sequence_number"])

    async def account_resource(
        self, account_address, resource_type: str
    ) -> Optional[Dict[str, Any]]:
        response = await self.client.get(
            f"{self.base_url}/accounts/{account_address}/resource/{resource_type}"
        )
        if response.status == 404:
            return None
        if response.status >= 400:
            raise ApiError(f"{await response.text()} - {account_address}", response.status)
        return await response.json()

    async def info(self) -> Dict[str, str]:
        response = await self.client.get(self.base_url)
        if response.status >= 400:
            raise ApiError(await response.text(), response.status)
        return await response.json()

    async def submit_transaction(self, sender, payload: Dict[str, Any], gas_limit: str = "10000", gas_price: str = "100", sequence: str = None) -> str:
        """
        1) Generates a transaction request
        2) submits that to produce a raw transaction
        3) signs the raw transaction
        4) submits the signed transaction
        """
        sender_address = sender.address()
        if sequence is None:
            sequence = str(await self.account_sequence_number(sender_address))
        txn_request = {
            "sender": f"{sender_address}",
            "sequence_number": sequence,
            "max_gas_amount": gas_limit,
            "gas_unit_price": gas_price,
            "expiration_timestamp_secs": str(int(time.time()) + 600),
            "payload": payload,
        }
        response = await self.client.post(
            f"{self.base_url}/transactions/encode_submission", json=txn_request
        )
        if response.status >= 400:
            raise ApiError(await response.text(), response.status)

        to_sign = bytes.fromhex((await response.json())[2:])
        signature = sender.sign(to_sign)
        txn_request["signature"] = {
            "type": "ed25519_signature",
            "public_key": f"{sender.public_key()}",
            "signature": f"{signature}",
        }

        headers = {"Content-Type": "application/json"}
        response = await self.client.post(
            f"{self.base_url}/transactions", headers=headers, json=txn_request
        )

        if response.status >= 400:
            raise ApiError(await response.text(), response.status)
        return (await response.json())["hash"]

    async def transaction_pending(self, txn_hash: str) -> bool:
        response = await self.client.get(f"{self.base_url}/transactions/by_hash/{txn_hash}")
        if response.status == 404:
            return True
        if response.status >= 400:
            raise ApiError(await response.text(), response.status)
        return (await response.json())["type"] == "pending_transaction"

    async def wait_for_transaction(self, txn_hash: str) -> None:
        """Waits up to 20 seconds for a transaction to move past pending state."""

        count = 0
        while await self.transaction_pending(txn_hash):
            assert count < 20, f"transaction {txn_hash} timed out"
            time.sleep(1)
            count += 1
        response = await self.client.get(f"{self.base_url}/transactions/by_hash/{txn_hash}")
        assert (
            "success" in (await response.json()) and (await response.json())["success"]
        ), f"{await response.text()} - {txn_hash}"

class ApiError(Exception):
    """Error thrown when the API returns >= 400"""

    def __init__(self, message, status_code):
        # Call the base class constructor with the parameters it needs
        super().__init__(message)
        self.status_code = status_code
