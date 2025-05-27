import logging
import time
import math
from typing import List, Dict, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import HyperliquidClient # To prevent circular import issues
from typing import Union # For type hinting initial_asset_contexts

# Helper functions for rounding and precision
def get_price_tick_size(asset_contexts: List[Dict], asset_name: str) -> Optional[float]:
    """Extracts the price tick size for a given asset from its metadata."""
    for asset in asset_contexts:
        if asset.get("name") == asset_name:
            # Assuming 'tickSize' is available in asset metadata
            # Example: "0.00001" -> 0.00001
            tick_size_str = asset.get("tickSize")
            if tick_size_str:
                try:
                    return float(tick_size_str)
                except ValueError:
                    logging.error(f"Invalid tickSize format for {asset_name}: {tick_size_str}")
                    return None
            else: # Fallback if tickSize is not directly available, try with 'szDecimals'
                # This is a guess, actual structure might differ.
                # If price is represented as an integer with fixed decimals,
                # tick size would be 10^(-num_decimals_for_price)
                # This part needs to be confirmed with actual API response for price representation
                logging.warning(f"tickSize not found for {asset_name}, attempting heuristic based on szDecimals if price were integer based.")
                # For instance, if price is like an integer, and szDecimals is for quantity, this might not apply.
                # This is a placeholder for a more robust way to get price precision if 'tickSize' isn't there.
                # num_price_decimals = asset.get("priceDecimals") # Hypothetical field
                # if num_price_decimals is not None:
                #    return 10 ** -int(num_price_decimals)
                return None # Default if no tick size info found
    return None

def get_size_decimals(asset_contexts: List[Dict], asset_name: str) -> Optional[int]:
    """Extracts the number of decimal places for order size for a given asset."""
    for asset in asset_contexts:
        if asset.get("name") == asset_name:
            # Assuming 'szDecimals' is available in asset metadata for quantity
            sz_decimals = asset.get("szDecimals")
            if sz_decimals is not None:
                try:
                    return int(sz_decimals)
                except ValueError:
                    logging.error(f"Invalid szDecimals format for {asset_name}: {sz_decimals}")
                    return None
    return None # Default if no size decimal info found

def round_price_to_tick(price: float, tick_size: float) -> float:
    """Rounds a price to the nearest valid tick size."""
    if tick_size is None or tick_size <= 0:
        logging.warning(f"Invalid tick_size {tick_size} for rounding price {price}. Returning original price.")
        return price
    return round(price / tick_size) * tick_size

def round_size_to_decimals(size: float, decimals: Optional[int]) -> float:
    """Rounds a size to the specified number of decimal places."""
    if decimals is None or decimals < 0:
        logging.warning(f"Invalid decimals {decimals} for rounding size {size}. Returning original size.")
        return size
    if decimals == 0:
        return math.floor(size) # Or math.trunc(size) depending on desired behavior for integers
    multiplier = 10 ** decimals
    return math.floor(size * multiplier) / multiplier # Using floor to not exceed desired size

def calculate_grid_levels(
    center_price: float,
    grid_spacing_percentage: float,
    num_levels: int
) -> List[float]:
    """
    Calculates buy and sell grid levels around a center price.
    num_levels: Total number of levels (e.g., 10 means 5 above, 5 below).
    Returns a sorted list of all grid price levels.
    """
    if num_levels <= 0:
        return []
    
    levels = []
    # Ensure an even number of levels for symmetry if desired, or adjust logic
    # For simplicity, if num_levels is odd, one side might have one more level
    # or the center_price itself could be considered a reference, not a grid line.
    # Here, we aim for roughly half above and half below.

    num_buy_levels = num_levels // 2
    num_sell_levels = num_levels - num_buy_levels

    # Sell levels (above center_price)
    for i in range(1, num_sell_levels + 1):
        levels.append(center_price * (1 + grid_spacing_percentage * i))

    # Buy levels (below center_price)
    for i in range(1, num_buy_levels + 1):
        levels.append(center_price * (1 - grid_spacing_percentage * i))
    
    levels.sort() # Ensure levels are sorted, buy levels first then sell levels
    return levels


class GridTrader:
    def __init__(
        self,
        client: 'HyperliquidClient',
        asset_name_main: str, # e.g., "HYPE"
        asset_name_quote: str, # e.g., "USDC"
        grid_spacing_percentage: float,
        num_grid_levels: int,
        base_order_size_quote: float, # Order size in terms of the quote asset (e.g., USDC)
        loop_interval_seconds: int,
        initial_asset_contexts: Union[List[Dict], Dict] # Added parameter
    ):
        self.client = client
        self.initial_asset_contexts = initial_asset_contexts # Store the passed contexts
        self.asset_name_main = asset_name_main
        self.asset_name_quote = asset_name_quote
        self.grid_spacing_percentage = grid_spacing_percentage
        self.num_grid_levels = num_grid_levels
        self.base_order_size_quote = base_order_size_quote
        self.loop_interval_seconds = loop_interval_seconds

        self.current_grid_levels: List[float] = []
        self.active_orders: Dict[str, Dict] = {}  # Store active order details, key by client_order_id or oid
        self.center_price: Optional[float] = None

        # Asset specific details (to be fetched)
        self.asset_index_main: Optional[int] = None # If API uses indices
        self.asset_index_quote: Optional[int] = None # If API uses indices
        self.price_tick_size_main: Optional[float] = None
        self.size_decimals_main: Optional[int] = None
        self.min_order_size_main: Optional[float] = None # Minimum quantity in main asset

        self.is_initialized = False
        logging.info("GridTrader initialized. Call resolve_asset_details() to proceed.")

    def _resolve_asset_details(self) -> bool:
        """
        Fetches asset metadata to determine indices, tick sizes, and decimal places.
        Uses pre-fetched asset_contexts provided during initialization.
        """
        logging.info("Resolving asset details using pre-fetched contexts...")
        
        asset_contexts_input = self.initial_asset_contexts
        asset_contexts: List[Dict]

        if isinstance(asset_contexts_input, dict) and "universe" in asset_contexts_input:
            asset_contexts = asset_contexts_input["universe"]
        elif isinstance(asset_contexts_input, list):
            asset_contexts = asset_contexts_input
        else:
            logging.error("Initial asset contexts are not in the expected format (list or dict with 'universe' key).")
            return False

        if not asset_contexts:
            logging.error("No asset data found in the provided initial asset contexts.")
            return False
            
        found_main = False
        found_quote = False

        for asset_info in asset_contexts:
            name = asset_info.get("name")
            if name == self.asset_name_main:
                self.asset_index_main = asset_info.get("asset_index") # Assuming 'asset_index' field exists
                self.price_tick_size_main = get_price_tick_size(asset_contexts, self.asset_name_main)
                self.size_decimals_main = get_size_decimals(asset_contexts, self.asset_name_main)
                # Assuming 'minOrderSize' field exists in asset metadata and it's in terms of the main asset
                min_order_size_str = asset_info.get("minOrderSize") 
                if min_order_size_str:
                    try:
                        self.min_order_size_main = float(min_order_size_str)
                    except ValueError:
                        logging.error(f"Invalid minOrderSize format for {self.asset_name_main}: {min_order_size_str}")

                logging.info(f"Details for {self.asset_name_main}: Index={self.asset_index_main}, TickSize={self.price_tick_size_main}, SizeDecimals={self.size_decimals_main}, MinOrderSz={self.min_order_size_main}")
                found_main = True
            elif name == self.asset_name_quote:
                self.asset_index_quote = asset_info.get("asset_index")
                logging.info(f"Details for {self.asset_name_quote}: Index={self.asset_index_quote}")
                found_quote = True
        
        if not found_main:
            logging.error(f"Could not resolve details for main asset: {self.asset_name_main}")
            return False
        # Quote asset details might not be strictly needed for trading HYPE/USDC if orders are defined in HYPE and USDC values
        # but good to confirm it exists.

        if self.price_tick_size_main is None or self.size_decimals_main is None:
            logging.error(f"Missing critical precision info (tick size or size decimals) for {self.asset_name_main}.")
            return False
        
        # If API uses asset names directly for orders, indices might be optional for client.place_order
        # but good to have them.
        # if self.asset_index_main is None: # Assuming 0 is a valid index
        #     logging.error(f"Asset index for {self.asset_name_main} not found.")
        #     return False

        self.is_initialized = True
        logging.info("Asset details resolved successfully.")
        return True

    def _update_market_data(self) -> Optional[float]:
        """
        Fetches the current mid-price for the trading pair.
        This is a placeholder. Real implementation would get order book or recent trades.
        """
        # For now, using a public endpoint that might give a mark price or index price.
        # This needs to be replaced with a more robust way to get current market price.
        # e.g., from info.all_mids() or by fetching order book snapshot.
        all_mids_response = self.client._make_public_request("info") # Assuming 'info' has all_mids or similar

        if all_mids_response and isinstance(all_mids_response, dict) and "allMids" in all_mids_response:
            mids = all_mids_response["allMids"]
            if self.asset_name_main in mids:
                try:
                    current_price = float(mids[self.asset_name_main])
                    logging.info(f"Current mid price for {self.asset_name_main}: {current_price}")
                    return current_price
                except ValueError:
                    logging.error(f"Invalid price format for {self.asset_name_main} in allMids: {mids[self.asset_name_main]}")
                    return None
            else:
                logging.warning(f"Mid price for {self.asset_name_main} not found in allMids response.")
                return None
        else:
            logging.warning(f"Could not fetch or parse allMids. Response: {all_mids_response}")
            return None

    def _update_balances(self):
        """
        Fetches current balances for main and quote assets.
        Placeholder: Actual implementation depends on client.get_user_state() response structure.
        """
        user_state = self.client.get_user_state()
        if user_state and isinstance(user_state, dict):
            # Assuming user_state contains 'assetPositions' or similar
            # The structure of user_state needs to be known from Hyperliquid API docs
            # Example structure: user_state.get("assetPositions", []) may list assets held by user
            # For each asset, it might have details like: {"asset": "HYPE", "position": {"qty": "10.5", "entry_px": "..."}}
            # Or it might be in user_state.get("crossAccountState", {}).get("balances")
            # This is highly dependent on the actual API response.
            logging.info("User state received (structure needs parsing based on actual API):")
            # logging.info(json.dumps(user_state, indent=2)) # Be careful with logging sensitive data

            # Placeholder: Extract main and quote asset balances
            # main_asset_balance = ...
            # quote_asset_balance = ...
            # logging.info(f"Balances: {self.asset_name_main}={main_asset_balance}, {self.asset_name_quote}={quote_asset_balance}")
            pass # Implement parsing based on actual user_state structure
        else:
            logging.warning("Could not fetch user state for balance update.")


    def _adjust_grid_and_place_orders(self, current_market_price: float):
        """
        Adjusts the grid based on the new market price and places/cancels orders.
        """
        if not self.is_initialized or self.price_tick_size_main is None or self.size_decimals_main is None:
            logging.error("Trader not initialized with asset details. Cannot adjust grid.")
            return

        # For now, let's assume the center_price is always the current_market_price.
        # More sophisticated logic might use a moving average or keep the grid static until significant drift.
        self.center_price = current_market_price
        
        new_grid_levels = calculate_grid_levels(
            self.center_price,
            self.grid_spacing_percentage,
            self.num_grid_levels
        )
        self.current_grid_levels = [round_price_to_tick(p, self.price_tick_size_main) for p in new_grid_levels]
        
        logging.info(f"New grid levels calculated around center {self.center_price}: {self.current_grid_levels}")

        # Naive approach: Cancel all existing orders and place new ones.
        # TODO: More sophisticated logic to only cancel/place orders that are truly new or need adjustment.
        self._cancel_all_orders() # Implement this method

        for price_level in self.current_grid_levels:
            if price_level == self.center_price: # Don't place order at center
                continue

            is_buy = price_level < self.center_price
            
            # Calculate order size in main asset
            # base_order_size_quote is e.g. 20 USDC. Size in HYPE = 20 / price_level
            order_size_main = self.base_order_size_quote / price_level
            rounded_order_size = round_size_to_decimals(order_size_main, self.size_decimals_main)

            if self.min_order_size_main and rounded_order_size < self.min_order_size_main:
                logging.warning(f"Calculated order size {rounded_order_size} for {self.asset_name_main} at price {price_level} is below minimum {self.min_order_size_main}. Skipping.")
                continue
            
            if rounded_order_size <= 0:
                logging.warning(f"Calculated order size is zero or negative for {self.asset_name_main} at price {price_level}. Skipping.")
                continue

            logging.info(f"Placing {'BUY' if is_buy else 'SELL'} order: {rounded_order_size} {self.asset_name_main} @ {price_level}")
            
            # The asset_name parameter in client.place_order should be the main asset (e.g., "HYPE")
            # for a HYPE/USDC pair.
            order_response = self.client.place_order(
                asset_name=self.asset_name_main, # Asset being traded
                is_buy=is_buy,
                limit_px=price_level,
                sz=rounded_order_size,
                reduce_only=False # Grid orders are typically not reduce_only
            )

            if order_response and order_response.get("status") == "ok":
                try:
                    # Assuming the response contains order details including an OID
                    # This structure depends on the actual response from client.place_order
                    order_status = order_response["response"]["data"]["statuses"][0]
                    if "Ok" in order_status:
                        oid = order_status["Ok"]["oid"]
                        # Store the active order, e.g., by its OID
                        self.active_orders[str(oid)] = {
                            "oid": oid,
                            "asset": self.asset_name_main,
                            "price": price_level,
                            "size": rounded_order_size,
                            "is_buy": is_buy
                        }
                        logging.info(f"Order placed successfully. OID: {oid}")
                    elif "Err" in order_status:
                         logging.error(f"Order placement failed for price {price_level}. Error: {order_status['Err']}")
                    else:
                        logging.error(f"Order placement status unknown for price {price_level}: {order_status}")

                except (KeyError, IndexError, TypeError) as e:
                    logging.error(f"Error parsing order placement response: {e} - Response: {order_response}")
            else:
                logging.error(f"Order placement failed for price {price_level}. Response: {order_response}")


    def _cancel_all_orders(self):
        """Cancels all active orders for the traded asset."""
        if not self.active_orders:
            logging.info("No active orders to cancel.")
            return

        logging.info(f"Cancelling {len(self.active_orders)} active orders for {self.asset_name_main}...")
        # Create a copy of items to iterate over, as self.active_orders might be modified
        orders_to_cancel = list(self.active_orders.items())

        for oid_str, order_data in orders_to_cancel:
            oid = order_data["oid"] # Assuming 'oid' is stored correctly
            asset_name = order_data["asset"] # Should be self.asset_name_main

            logging.info(f"Cancelling order OID: {oid} for asset {asset_name}")
            cancel_response = self.client.cancel_order(asset_name=asset_name, oid=oid)

            if cancel_response and cancel_response.get("status") == "ok":
                # Assuming the response indicates success, e.g., via statuses
                # The actual success check depends on client.cancel_order response structure
                cancel_data = cancel_response.get("response", {}).get("data", {})
                if cancel_data.get("statuses") and "success" in cancel_data.get("statuses", []): # Example check
                    logging.info(f"Order OID: {oid} cancelled successfully.")
                    # Remove from active orders if cancellation is confirmed by the exchange
                    if oid_str in self.active_orders:
                         del self.active_orders[oid_str]
                else:
                    logging.warning(f"Order OID: {oid} cancellation status unclear or failed in response: {cancel_response}")
            else:
                logging.error(f"Failed to send cancel request for order OID: {oid}. Response: {cancel_response}")
        
        # Verify if active_orders is empty or log remaining ones
        if self.active_orders:
            logging.warning(f"{len(self.active_orders)} orders might remain active after cancellation attempts.")
        else:
            logging.info("All tracked active orders have been processed for cancellation.")


    def _handle_filled_orders(self):
        """
        Checks for filled orders, updates balances/positions, and potentially re-establishes grid levels.
        Placeholder: This requires checking order statuses or trade history.
        """
        # This would typically involve:
        # 1. Fetching open orders: client.get_open_orders(self.asset_name_main)
        # 2. Comparing with self.active_orders to find orders that are no longer open (i.e., filled or cancelled externally)
        # 3. Fetching trade history: client.get_fills() or similar
        # 4. For each fill, log it, update local representation of position.
        # 5. If a grid order is filled, a new order on the opposite side might be placed
        #    further out, or the grid re-centered. For simplicity, our current main loop
        #    re-evaluates the whole grid based on current price.

        # For now, this is a stub. The current loop's _adjust_grid_and_place_orders
        # effectively rebuilds the grid from scratch each time, which implicitly handles
        # part of what this function would do (re-establishing orders).
        # However, it doesn't explicitly track fills or manage profit/loss from them.
        logging.debug("Checking for filled orders (placeholder)...")
        # If an order from self.active_orders is found to be filled, it should be removed.
        # Example:
        # completed_oids = self.client.get_filled_order_ids() # Hypothetical
        # for oid in completed_oids:
        #     if str(oid) in self.active_orders:
        #         logging.info(f"Order {oid} was filled: {self.active_orders[str(oid)]}")
        #         del self.active_orders[str(oid)]
        #         # Potentially trigger re-evaluation or specific logic for fills
        pass


    def run(self):
        """Main trading loop."""
        logging.info(f"Starting GridTrader for {self.asset_name_main}/{self.asset_name_quote}.")

        if not self.is_initialized:
            if not self._resolve_asset_details():
                logging.error("Failed to initialize asset details. Bot cannot start.")
                return
        
        logging.info("Trader initialized and asset details resolved.")
        logging.info(f"Trading Pair: {self.asset_name_main}/{self.asset_name_quote}")
        logging.info(f"Grid Spacing: {self.grid_spacing_percentage*100:.2f}%")
        logging.info(f"Grid Levels: {self.num_grid_levels}")
        logging.info(f"Base Order Size (Quote): {self.base_order_size_quote} {self.asset_name_quote}")
        logging.info(f"Price Tick Size ({self.asset_name_main}): {self.price_tick_size_main}")
        logging.info(f"Size Decimals ({self.asset_name_main}): {self.size_decimals_main}")
        logging.info(f"Min Order Size ({self.asset_name_main}): {self.min_order_size_main}")


        try:
            while True:
                logging.info("--- Starting new trading loop iteration ---")
                
                # 1. Update market data (current price)
                current_price = self._update_market_data()
                if current_price is None:
                    logging.error("Could not fetch current market price. Skipping this iteration.")
                    time.sleep(self.loop_interval_seconds)
                    continue
                
                # 2. Update account balances (optional for this basic grid, but good practice)
                self._update_balances()

                # 3. Check for filled orders (and potentially adjust strategy based on fills)
                self._handle_filled_orders() # Placeholder for now

                # 4. Adjust grid and place/cancel orders
                self._adjust_grid_and_place_orders(current_price)
                
                logging.info(f"--- Trading loop iteration finished. Active orders: {len(self.active_orders)} ---")
                logging.info(f"Waiting for {self.loop_interval_seconds} seconds...")
                time.sleep(self.loop_interval_seconds)

        except KeyboardInterrupt:
            logging.info("GridTrader run loop interrupted by user.")
        except Exception as e:
            logging.error(f"An unexpected error occurred in the GridTrader run loop: {e}", exc_info=True)
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources, e.g., cancel all open orders."""
        logging.info("Initiating cleanup: Cancelling all open orders...")
        self._cancel_all_orders()
        logging.info("Cleanup finished.")


if __name__ == '__main__':
    # This is for basic testing of the GridTrader structure, not full execution.
    # Full execution requires a running HyperliquidClient and network interaction.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Mock HyperliquidClient for testing purposes
    class MockHyperliquidClient:
        def __init__(self, api_key, api_secret, wallet_address):
            logging.info("MockHyperliquidClient initialized.")
            self.wallet_address = wallet_address

        def get_asset_contexts(self):
            # Simulate response structure from api_client.py
            return {
                "universe": [
                    {"name": "HYPE", "asset_index": 0, "tickSize": "0.001", "szDecimals": 3, "minOrderSize": "1.0"},
                    {"name": "USDC", "asset_index": 1, "tickSize": "0.000001", "szDecimals": 6}
                ]
            }

        def _make_public_request(self, endpoint): # For _update_market_data
            if endpoint == "info": # Crude mock for allMids
                return {"allMids": {"HYPE": "10.5"}} # Simulate current price of HYPE = 10.5 USDC
            return None

        def get_user_state(self): # For _update_balances
            logging.info(f"Mock: Fetching user state for {self.wallet_address}")
            return {"assetPositions": []} # Simulate empty positions

        def place_order(self, asset_name, is_buy, limit_px, sz, reduce_only=False):
            logging.info(f"Mock: Placing order: {asset_name}, Buy={is_buy}, Px={limit_px}, Sz={sz}")
            # Simulate successful order placement with an OID
            return {
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {"statuses": [{"Ok": {"oid": int(time.time()*1000) % 100000, "order": {}}}]}
                }
            }

        def cancel_order(self, asset_name, oid):
            logging.info(f"Mock: Cancelling order: {asset_name}, OID={oid}")
            return {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}}

    mock_client = MockHyperliquidClient("dummy_key", "dummy_secret", "0x123")

    trader = GridTrader(
        client=mock_client, #type: ignore
        asset_name_main="HYPE",
        asset_name_quote="USDC",
        grid_spacing_percentage=0.01, # 1%
        num_grid_levels=10,
        base_order_size_quote=20.0, # 20 USDC per order
        loop_interval_seconds=10,
        initial_asset_contexts=mock_client.get_asset_contexts() # Pass mock contexts
    )

    # Test initialization (which now uses the passed contexts)
    # _resolve_asset_details is called internally by run(), or can be called directly if needed for setup.
    # For this test, we'll call it directly to check its logic.
    if trader._resolve_asset_details(): # This will use the mock data passed to constructor
        logging.info("Trader asset details resolved successfully with mock data.")
        logging.info(f"Price tick size for HYPE: {trader.price_tick_size_main}")
        logging.info(f"Size decimals for HYPE: {trader.size_decimals_main}")

        # Test grid calculation
        test_center_price = 10.5
        levels = calculate_grid_levels(test_center_price, trader.grid_spacing_percentage, trader.num_grid_levels)
        logging.info(f"Calculated grid levels around {test_center_price}: {levels}")
        
        rounded_levels = [round_price_to_tick(p, trader.price_tick_size_main) for p in levels if trader.price_tick_size_main] #type: ignore
        logging.info(f"Rounded grid levels: {rounded_levels}")

        # Test a single cycle of adjust_grid_and_place_orders
        logging.info("--- Testing _adjust_grid_and_place_orders ---")
        current_mock_price = trader._update_market_data()
        if current_mock_price:
            trader._adjust_grid_and_place_orders(current_mock_price)
            logging.info(f"Active orders after adjustment: {len(trader.active_orders)}")
            # print(trader.active_orders)
        else:
            logging.error("Failed to get mock current price for testing adjustment.")
        
        logging.info("--- Testing _cancel_all_orders ---")
        trader._cancel_all_orders()
        logging.info(f"Active orders after cancellation: {len(trader.active_orders)}")

    else:
        logging.error("Trader asset details resolution failed with mock data.")

    logging.info("Basic GridTrader test structure finished.")
    # To run the bot: trader.run() (but this would loop indefinitely with mock)
