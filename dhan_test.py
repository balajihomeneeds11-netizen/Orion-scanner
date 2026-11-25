
import os
import time
from dhanhq import DhanContext, MarketFeed

CLIENT_ID = os.environ["DHAN_CLIENT_ID"]
ACCESS_TOKEN = os.environ["DHAN_ACCESS_TOKEN"]

context = DhanContext(CLIENT_ID, ACCESS_TOKEN)

# HDFC Bank - NSE
instruments = [
    (MarketFeed.NSE, "1333", MarketFeed.Ticker)
]

feed = MarketFeed(
    context,
    instruments,
    version="v2"
)

print("Connecting to Dhan WebSocket...")

try:
    feed.run_forever()
    print("Dhan connection started!")

    while True:
        data = feed.get_data()
        if data:
            print("LIVE DATA:", data)
        time.sleep(0.1)

except KeyboardInterrupt:
    print("Stopping feed...")
    feed.close_connection()

except Exception as error:
    print("ERROR:", error)
  
