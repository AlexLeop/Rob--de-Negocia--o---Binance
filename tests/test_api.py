import asyncio, os
from dotenv import load_dotenv
from binance import AsyncClient

async def run():
    load_dotenv()
    client = await AsyncClient.create(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'), testnet=True)
    try:
        balance = await client.futures_account_balance()
        print(balance)
    except Exception as e:
        print("API Error:", e)
    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(run())
