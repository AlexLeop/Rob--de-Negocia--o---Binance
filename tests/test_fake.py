import asyncio
from binance import AsyncClient

async def run():
    client = await AsyncClient.create('fake_key', 'fake_secret', testnet=True)
    try:
        balance = await client.futures_account_balance()
        print(balance)
    except Exception as e:
        print("API Error:", e)
    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(run())
