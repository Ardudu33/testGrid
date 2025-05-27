# Hyperliquid HYPE/USDC Spot Grid Trading Bot

This Python bot implements a grid trading strategy for the HYPE/USDC spot pair on the Hyperliquid decentralized exchange. It automatically places buy and sell orders based on a predefined grid, adjusting to market movements.

**Disclaimer:** This bot is provided as a foundational framework. Trading cryptocurrencies involves significant risk. You are solely responsible for your trading decisions and any losses incurred. **Thoroughly test this bot with small amounts in a live environment before committing significant capital.** The authors and contributors are not liable for any financial losses.

## Prerequisites

*   Python 3.7+
*   pip (Python package installer)
*   Access to the Hyperliquid exchange and an account (wallet).
*   **Hyperliquid Python SDK**: You will need to obtain and integrate the official Hyperliquid Python SDK for generating request signatures. This bot **will not function for trading** without it.

## Installation

1.  **Clone the Repository (if applicable):**
    If you have this bot as part of a Git repository, clone it:
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```
    If you only have the script files, create a project directory and place them inside.

2.  **Set up a Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    Create a `requirements.txt` file (if you don't have it from the previous steps) with the following content:
    ```txt
    requests
    python-dotenv
    # Add the Hyperliquid SDK here if it's pip-installable
    # e.g., hyperliquid-sdk-xyz
    ```
    Then install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

1.  **Create `.env` file:**
    Copy the example environment file to a new `.env` file:
    ```bash
    cp .env.example .env
    ```

2.  **Edit `.env` file:**
    Open `.env` in a text editor and fill in your details:

    *   `HYPERLIQUID_API_KEY`: Your Hyperliquid API Key (if applicable, some DEXs might only use wallet signatures).
    *   `HYPERLIQUID_API_SECRET`: **Your Hyperliquid API Secret (Private Key for signing). Treat this like a password!**
    *   `HYPERLIQUID_WALLET_ADDRESS`: Your wallet address (e.g., `0xYourWalletAddress...`).

    *   `HYPE_ASSET_NAME`: Name of the base asset (default: "HYPE").
    *   `USDC_ASSET_NAME`: Name of the quote asset (default: "USDC").
    *   `GRID_SPACING`: Percentage spacing between grid levels (e.g., `0.005` for 0.5%).
    *   `GRID_LEVELS`: Total number of grid levels (e.g., `10` for 5 buy levels and 5 sell levels).
    *   `BASE_ORDER_SIZE_USDC`: The desired value of each individual order in USDC (e.g., `20.0`).
    *   `LOOP_INTERVAL_SECONDS`: Time in seconds between each cycle of the bot's main loop (e.g., `60`).

    *   `HYPERLIQUID_SDK_PATH` (Optional): If your Hyperliquid SDK is not installed in standard Python paths, provide the absolute path to its directory here.

## Critical: Hyperliquid SDK Integration

This bot framework includes an `api_client.py` file that handles communication with the Hyperliquid API. However, to place or cancel orders (i.e., interact with the `/exchange` endpoint), requests must be cryptographically signed.

**You MUST integrate the official Hyperliquid Python SDK's signing mechanism into `api_client.py`**.

*   Locate the `sign_l1_action` function (or its equivalent) within the SDK.
*   Modify the `_post_exchange` method in `api_client.py`, particularly the section marked with `--- Placeholder for Hyperliquid SDK Signature Generation ---` and the usage of `sign_l1_action`.
*   Ensure the SDK is correctly imported and that your `HYPERLIQUID_API_SECRET` (private key) is securely passed to the signing function as per the SDK's requirements.

**Without successful SDK integration for signing, the bot will NOT be able to execute any trades.** The placeholder signing logic will fail authentication.

## Running the Bot

Once configured, and **after you have integrated the SDK's signing mechanism**, you can run the bot:

```bash
python grid_bot.py
```

The bot will start logging its actions to the console. It will:
1.  Load configuration.
2.  Initialize the API client.
3.  Fetch asset information and balances.
4.  Calculate the initial grid and start placing orders.
5.  Periodically update prices, balances, and adjust the grid as needed.

## Logging

The bot logs information to the console, including:
*   Initialization parameters.
*   Current market prices and balances.
*   Grid calculations.
*   Orders placed and cancelled (with their IDs).
*   Grid adjustments.
*   Errors encountered.

For persistent logging, you can redirect the output to a file:
```bash
python grid_bot.py > bot.log 2>&1 &
```

## Important Notes & Limitations

*   **Test Thoroughly:** Start with very small `BASE_ORDER_SIZE_USDC` values to understand the bot's behavior and ensure it interacts correctly with the exchange.
*   **API Behavior:** The bot's parsing of API responses (for order IDs, balances, errors) is based on the provided API documentation. This may need adjustments if the live API behaves differently. Verify these parts carefully.
*   **Order Status Tracking:** This version of the bot has a simplified approach to tracking filled orders. For robust operation, it's highly recommended to:
    *   Check if Hyperliquid offers an API endpoint to query current open orders or order status by ID.
    *   Integrate this into the `_cleanup_filled_orders` method in `trader.py` to accurately reconcile the bot's internal state with the exchange.
*   **Price & Size Precision:** Ensure the price and size rounding logic in `trader.py` (functions like `round_price_to_tick`, `round_size_to_decimals`) aligns with Hyperliquid's requirements for the HYPE/USDC pair. These are often found in the exchange's API documentation or asset metadata.
*   **Error Handling:** While basic error handling is in place, you may want to enhance it for specific API errors or network issues (e.g., implementing retry mechanisms with backoff).
*   **Concurrency:** This bot runs in a single thread. For high-frequency operations or managing many pairs, a more complex asynchronous architecture might be needed.

Good luck, and trade responsibly!
