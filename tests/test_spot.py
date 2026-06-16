import asyncio, os
from dotenv import load_dotenv
from binance import AsyncClient

async def run():
    load_dotenv()
    client = await AsyncClient.create(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'), testnet=True)
    try:
        # Override for spot testnet
        client.API_URL = "https://testnet.binance.vision/api"
        balance = await client.get_account()
        print("Success, spot account has:", len(balance['balances']), "balances")
    except Exception as e:
        print("API Error:", e)
    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(run())
