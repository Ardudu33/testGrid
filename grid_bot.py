# Main application file for the Hyperliquid Grid Trading Bot
import logging
import time # time module is not explicitly used here but often useful in bot scripts
import os
from typing import Optional, List, Dict, Union
from dotenv import load_dotenv

from api_client import HyperliquidClient
from trader import GridTrader

def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Starting Grid Trading Bot...")

    # Load configuration from environment variables
    API_KEY = os.getenv("HYPERLIQUID_API_KEY") # api_client.py's constructor includes api_key
    API_SECRET = os.getenv("HYPERLIQUID_API_SECRET")
    WALLET_ADDRESS = os.getenv("HYPERLIQUID_WALLET_ADDRESS")

    HYPE_ASSET_NAME = os.getenv("HYPE_ASSET_NAME", "HYPE")
    USDC_ASSET_NAME = os.getenv("USDC_ASSET_NAME", "USDC") # Quote asset
    GRID_SPACING_STR = os.getenv("GRID_SPACING", "0.005")
    GRID_LEVELS_STR = os.getenv("GRID_LEVELS", "10")
    BASE_ORDER_SIZE_USDC_STR = os.getenv("BASE_ORDER_SIZE_USDC", "20.0")
    LOOP_INTERVAL_SECONDS_STR = os.getenv("LOOP_INTERVAL_SECONDS", "60")

    # Validate and convert parameters
    missing_vars = []
    # API_KEY can be an empty string if not strictly required by all API endpoints,
    # but the HyperliquidClient constructor in api_client.py expects it.
    if API_KEY is None: missing_vars.append("HYPERLIQUID_API_KEY (can be empty if auth method doesn't need it)")
    if not API_SECRET: missing_vars.append("HYPERLIQUID_API_SECRET")
    if not WALLET_ADDRESS: missing_vars.append("HYPERLIQUID_WALLET_ADDRESS")

    if missing_vars:
        logging.error(f"Missing critical environment variables: {', '.join(missing_vars)}. Exiting.")
        return

    try:
        GRID_SPACING = float(GRID_SPACING_STR)
        GRID_LEVELS = int(GRID_LEVELS_STR)
        BASE_ORDER_SIZE_USDC = float(BASE_ORDER_SIZE_USDC_STR)
        LOOP_INTERVAL_SECONDS = int(LOOP_INTERVAL_SECONDS_STR)
    except ValueError as e:
        logging.error(f"Invalid format for one or more numeric environment variables: {e}. Exiting.")
        return

    logging.info("Configuration loaded:")
    logging.info(f"  WALLET_ADDRESS: {WALLET_ADDRESS}") # Okay to log wallet address
    logging.info(f"  HYPE_ASSET_NAME: {HYPE_ASSET_NAME}")
    logging.info(f"  USDC_ASSET_NAME: {USDC_ASSET_NAME}")
    logging.info(f"  GRID_SPACING: {GRID_SPACING*100:.2f}%")
    logging.info(f"  GRID_LEVELS: {GRID_LEVELS}")
    logging.info(f"  BASE_ORDER_SIZE_USDC: {BASE_ORDER_SIZE_USDC}")
    logging.info(f"  LOOP_INTERVAL_SECONDS: {LOOP_INTERVAL_SECONDS}")

    # Initialize HyperliquidClient
    # The constructor in api_client.py takes api_key, api_secret, wallet_address.
    client = HyperliquidClient(
        api_key=API_KEY, 
        api_secret=API_SECRET, 
        wallet_address=WALLET_ADDRESS
    )
    logging.info("HyperliquidClient initialized.")

    # Fetch Initial Asset Metadata
    # The method in api_client.py is get_asset_contexts(), not get_spot_asset_contexts().
    # It returns a dictionary like {"universe": [...]} based on current api_client.py.
    logging.info("Fetching initial asset metadata...")
    raw_asset_contexts = client.get_asset_contexts() 
    
    initial_spot_meta_tokens: Union[List[Dict], None] = None

    if raw_asset_contexts:
        if isinstance(raw_asset_contexts, dict) and "universe" in raw_asset_contexts:
            initial_spot_meta_tokens = raw_asset_contexts["universe"]
            if not isinstance(initial_spot_meta_tokens, list):
                logging.error(f"'universe' key does not contain a list. Found: {type(initial_spot_meta_tokens)}. Exiting.")
                return
        elif isinstance(raw_asset_contexts, list): # If the client was changed to return list directly
            initial_spot_meta_tokens = raw_asset_contexts
        else:
            logging.error(f"Unexpected format for asset contexts: {type(raw_asset_contexts)}. Expected dict with 'universe' or list. Exiting.")
            return
        
        if not initial_spot_meta_tokens:
            logging.error("No asset metadata found in 'universe' or the list is empty. Exiting.")
            return
        logging.info(f"Successfully fetched and parsed asset metadata. Found {len(initial_spot_meta_tokens)} assets.")
    else:
        logging.error("Failed to fetch asset contexts from the API. Exiting.")
        return

    trader: Optional[GridTrader] = None
    try:
        # Initialize GridTrader
        trader = GridTrader(
            client=client,
            asset_name_main=HYPE_ASSET_NAME,
            asset_name_quote=USDC_ASSET_NAME,
            grid_spacing_percentage=GRID_SPACING,
            num_grid_levels=GRID_LEVELS,
            base_order_size_quote=BASE_ORDER_SIZE_USDC,
            loop_interval_seconds=LOOP_INTERVAL_SECONDS,
            initial_asset_contexts=initial_spot_meta_tokens # Pass the fetched metadata
        )
        # GridTrader's run() method will call _resolve_asset_details internally.
        # _resolve_asset_details will set trader.is_initialized.
        # If it fails, trader.run() should exit gracefully.
        logging.info("GridTrader initialized.")

        # Start the trading loop
        trader.run() # This will first attempt to resolve asset details using the provided contexts.

    except KeyboardInterrupt:
        logging.info("Bot stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logging.error(f"A critical error occurred in the main application: {e}", exc_info=True)
    finally:
        logging.info("Shutting down bot...")
        if trader:
            logging.info("Calling trader.cleanup()...")
            trader.cleanup()
        else:
            logging.info("Trader was not (or not fully) initialized, no specific trader cleanup needed.")
        logging.info("Bot shutdown complete.")

if __name__ == "__main__":
    main()
