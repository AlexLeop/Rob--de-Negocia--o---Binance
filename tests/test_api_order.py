import asyncio, os
from dotenv import load_dotenv
from binance import AsyncClient

async def run():
    load_dotenv()
    client = await AsyncClient.create(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'), testnet=True)
    try:
        res = await client.futures_create_order(
            symbol="BTCUSDT",
            side="BUY",
            type="MARKET",
            quantity=0.001
        )
        print("Success:", res)
    except Exception as e:
        print("API Error:", e)
    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(run())
