"""
Production-Grade FIFO Cost of Goods Sold (COGS) System

This system implements a complete FIFO inventory valuation method with:
- Layer-based inventory tracking
- Full auditability and traceability
- Edge case handling (returns, adjustments, partial consumption)
- Batch processing and real-time transaction support
- Performance optimizations
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Tuple
from enum import Enum
import uuid
from collections import defaultdict


class TransactionType(Enum):
    """Types of inventory transactions"""
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    RETURN = "RETURN"
    ADJUSTMENT = "ADJUSTMENT"


class ReturnPolicy(Enum):
    """Policy for handling returns"""
    RESTORE_ORIGINAL_LAYER = "RESTORE_ORIGINAL_LAYER"  # Restore to original purchase layer
    CREATE_NEW_LAYER = "CREATE_NEW_LAYER"  # Create new layer at current cost


@dataclass
class InventoryLayer:
    """
    Represents a single inventory layer (lot) with FIFO tracking.
    
    Attributes:
        id: Unique identifier for the layer
        product_id: Product identifier
        remaining_qty: Quantity remaining in this layer
        unit_cost: Cost per unit for this layer
        created_at: Timestamp when layer was created
        original_purchase_id: Reference to original purchase transaction
        expiry_date: Optional expiry date for perishable goods
        warehouse_id: Optional warehouse identifier for multi-warehouse support
    """
    id: str
    product_id: str
    remaining_qty: float
    unit_cost: float
    created_at: datetime
    original_purchase_id: str
    expiry_date: Optional[datetime] = None
    warehouse_id: Optional[str] = None
    
    def __post_init__(self):
        if self.remaining_qty < 0:
            raise ValueError(f"Layer {self.id} cannot have negative quantity")
        if self.unit_cost < 0:
            raise ValueError(f"Layer {self.id} cannot have negative unit cost")


@dataclass
class InventoryTransaction:
    """
    Represents an inventory transaction (immutable audit log).
    
    Attributes:
        id: Unique identifier for the transaction
        product_id: Product identifier
        type: Type of transaction (PURCHASE, SALE, RETURN, ADJUSTMENT)
        quantity: Quantity affected (positive for additions, negative for removals)
        unit_price: Price per unit (for sales/purchases)
        unit_cost: Cost per unit (for purchases)
        timestamp: When the transaction occurred
        reference_id: External reference (e.g., order number)
        warehouse_id: Optional warehouse identifier
        metadata: Additional transaction metadata
    """
    id: str
    product_id: str
    type: TransactionType
    quantity: float
    unit_price: Optional[float] = None
    unit_cost: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    reference_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    def __post_init__(self):
        if self.type == TransactionType.PURCHASE and self.quantity <= 0:
            raise ValueError(f"Purchase transaction {self.id} must have positive quantity")
        if self.type == TransactionType.SALE and self.quantity <= 0:
            raise ValueError(f"Sale transaction {self.id} must have positive quantity")


@dataclass
class COGSEntry:
    """
    Records the COGS allocation for a specific sale.
    
    Attributes:
        id: Unique identifier
        sale_id: Reference to the sale transaction
        layer_id: Reference to the inventory layer consumed
        quantity_taken: Quantity taken from this layer
        unit_cost: Cost per unit from this layer
        total_cost: Total cost (quantity_taken * unit_cost)
        timestamp: When the COGS was calculated
    """
    id: str
    sale_id: str
    layer_id: str
    quantity_taken: float
    unit_cost: float
    total_cost: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        self.total_cost = self.quantity_taken * self.unit_cost


class InsufficientInventoryError(Exception):
    """Raised when attempting to sell more than available inventory"""
    pass


class NegativeInventoryError(Exception):
    """Raised when inventory would go negative"""
    pass


class FIFOInventorySystem:
    """
    Production-grade FIFO inventory management system.
    
    Features:
    - Layer-based FIFO tracking
    - Full audit trail
    - Edge case handling
    - Performance optimized with indexing
    - Support for returns and adjustments
    """
    
    def __init__(self, allow_negative_inventory: bool = False, 
                 return_policy: ReturnPolicy = ReturnPolicy.RESTORE_ORIGINAL_LAYER):
        """
        Initialize the FIFO inventory system.
        
        Args:
            allow_negative_inventory: Whether to allow inventory to go negative
            return_policy: Policy for handling returned goods
        """
        self.allow_negative_inventory = allow_negative_inventory
        self.return_policy = return_policy
        
        # Data storage (in production, use a database with proper indexing)
        self.layers: Dict[str, InventoryLayer] = {}  # layer_id -> layer
        self.transactions: Dict[str, InventoryTransaction] = {}  # transaction_id -> transaction
        self.cogs_entries: List[COGSEntry] = []
        
        # Indexes for performance
        self.layers_by_product: Dict[str, List[str]] = defaultdict(list)  # product_id -> [layer_ids]
        self.transactions_by_product: Dict[str, List[str]] = defaultdict(list)  # product_id -> [transaction_ids]
        self.cogs_by_sale: Dict[str, List[COGSEntry]] = defaultdict(list)  # sale_id -> [cogs_entries]
        
    def _generate_id(self) -> str:
        """Generate a unique identifier"""
        return str(uuid.uuid4())
    
    def _get_layers_fifo(self, product_id: str, warehouse_id: Optional[str] = None) -> List[InventoryLayer]:
        """
        Get inventory layers for a product in FIFO order (oldest first).
        
        Args:
            product_id: Product identifier
            warehouse_id: Optional warehouse filter
            
        Returns:
            List of layers sorted by creation date (oldest first)
        """
        layer_ids = self.layers_by_product.get(product_id, [])
        layers = [self.layers[lid] for lid in layer_ids if self.layers[lid].remaining_qty > 0]
        
        # Filter by warehouse if specified
        if warehouse_id:
            layers = [l for l in layers if l.warehouse_id == warehouse_id]
        
        # Sort by creation date (FIFO)
        layers.sort(key=lambda x: x.created_at)
        
        # Also sort by expiry date if available (FEFO - First Expired, First Out)
        layers.sort(key=lambda x: x.expiry_date if x.expiry_date else datetime.max)
        
        return layers
    
    def _get_total_inventory(self, product_id: str, warehouse_id: Optional[str] = None) -> float:
        """
        Get total available inventory for a product.
        
        Args:
            product_id: Product identifier
            warehouse_id: Optional warehouse filter
            
        Returns:
            Total quantity available
        """
        layers = self._get_layers_fifo(product_id, warehouse_id)
        return sum(layer.remaining_qty for layer in layers)
    
    def record_purchase(self, product_id: str, quantity: float, unit_cost: float,
                       reference_id: Optional[str] = None,
                       warehouse_id: Optional[str] = None,
                       expiry_date: Optional[datetime] = None,
                       metadata: Optional[Dict] = None) -> Tuple[str, str]:
        """
        Record a purchase transaction, creating a new inventory layer.
        
        Args:
            product_id: Product identifier
            quantity: Quantity purchased
            unit_cost: Cost per unit
            reference_id: External reference (e.g., PO number)
            warehouse_id: Optional warehouse identifier
            expiry_date: Optional expiry date
            metadata: Additional metadata
            
        Returns:
            Tuple of (transaction_id, layer_id)
        """
        transaction_id = self._generate_id()
        layer_id = self._generate_id()
        
        # Create transaction
        transaction = InventoryTransaction(
            id=transaction_id,
            product_id=product_id,
            type=TransactionType.PURCHASE,
            quantity=quantity,
            unit_cost=unit_cost,
            reference_id=reference_id,
            warehouse_id=warehouse_id,
            metadata=metadata or {}
        )
        
        # Create layer
        layer = InventoryLayer(
            id=layer_id,
            product_id=product_id,
            remaining_qty=quantity,
            unit_cost=unit_cost,
            created_at=transaction.timestamp,
            original_purchase_id=transaction_id,
            expiry_date=expiry_date,
            warehouse_id=warehouse_id
        )
        
        # Store
        self.transactions[transaction_id] = transaction
        self.layers[layer_id] = layer
        self.layers_by_product[product_id].append(layer_id)
        self.transactions_by_product[product_id].append(transaction_id)
        
        return transaction_id, layer_id
    
    def process_sale(self, product_id: str, quantity: float, unit_price: float,
                    reference_id: Optional[str] = None,
                    warehouse_id: Optional[str] = None,
                    metadata: Optional[Dict] = None) -> Tuple[str, float]:
        """
        Process a sale transaction using FIFO consumption logic.
        
        Args:
            product_id: Product identifier
            quantity: Quantity sold
            unit_price: Selling price per unit
            reference_id: External reference (e.g., order number)
            warehouse_id: Optional warehouse identifier
            metadata: Additional metadata
            
        Returns:
            Tuple of (transaction_id, total_cogs)
            
        Raises:
            InsufficientInventoryError: If not enough inventory available
        """
        transaction_id = self._generate_id()
        
        # Check inventory availability
        available = self._get_total_inventory(product_id, warehouse_id)
        if available < quantity and not self.allow_negative_inventory:
            raise InsufficientInventoryError(
                f"Insufficient inventory for product {product_id}. "
                f"Available: {available}, Requested: {quantity}"
            )
        
        # Create sale transaction
        transaction = InventoryTransaction(
            id=transaction_id,
            product_id=product_id,
            type=TransactionType.SALE,
            quantity=quantity,
            unit_price=unit_price,
            reference_id=reference_id,
            warehouse_id=warehouse_id,
            metadata=metadata or {}
        )
        
        # FIFO consumption logic
        layers = self._get_layers_fifo(product_id, warehouse_id)
        remaining = quantity
        total_cogs = 0.0
        
        for layer in layers:
            if remaining <= 0:
                break
            
            # Take as much as possible from current layer
            take_qty = min(layer.remaining_qty, remaining)
            cost = take_qty * layer.unit_cost
            
            # Record COGS entry
            cogs_entry = COGSEntry(
                id=self._generate_id(),
                sale_id=transaction_id,
                layer_id=layer.id,
                quantity_taken=take_qty,
                unit_cost=layer.unit_cost,
                total_cost=cost
            )
            
            self.cogs_entries.append(cogs_entry)
            self.cogs_by_sale[transaction_id].append(cogs_entry)
            
            # Update layer
            layer.remaining_qty -= take_qty
            remaining -= take_qty
            total_cogs += cost
            
            # Log layer depletion
            if layer.remaining_qty == 0:
                # Layer is fully consumed
                pass
        
        # Store transaction
        self.transactions[transaction_id] = transaction
        self.transactions_by_product[product_id].append(transaction_id)
        
        return transaction_id, total_cogs
    
    def process_return(self, product_id: str, quantity: float, original_sale_id: str,
                      reference_id: Optional[str] = None,
                      warehouse_id: Optional[str] = None,
                      metadata: Optional[Dict] = None) -> Tuple[str, float]:
        """
        Process a return transaction.
        
        Args:
            product_id: Product identifier
            quantity: Quantity returned
            original_sale_id: Reference to the original sale transaction
            reference_id: External reference (e.g., RMA number)
            warehouse_id: Optional warehouse identifier
            metadata: Additional metadata
            
        Returns:
            Tuple of (transaction_id, adjustment_amount)
        """
        transaction_id = self._generate_id()
        
        # Create return transaction
        transaction = InventoryTransaction(
            id=transaction_id,
            product_id=product_id,
            type=TransactionType.RETURN,
            quantity=quantity,  # Positive quantity for returns
            reference_id=reference_id,
            warehouse_id=warehouse_id,
            metadata=metadata or {}
        )
        
        adjustment_amount = 0.0
        
        if self.return_policy == ReturnPolicy.RESTORE_ORIGINAL_LAYER:
            # Restore to original layers used in the sale
            cogs_entries = self.cogs_by_sale.get(original_sale_id, [])
            
            if not cogs_entries:
                raise ValueError(f"No COGS entries found for sale {original_sale_id}")
            
            remaining = quantity
            
            for cogs in cogs_entries:
                if remaining <= 0:
                    break
                
                layer = self.layers[cogs.layer_id]
                restore_qty = min(cogs.quantity_taken, remaining)
                
                # Restore to original layer
                layer.remaining_qty += restore_qty
                adjustment_amount -= restore_qty * cogs.unit_cost  # Negative = reduce COGS
                remaining -= restore_qty
                
        else:  # CREATE_NEW_LAYER
            # Create new layer at current average cost or specified cost
            avg_cost = self._get_average_cost(product_id, warehouse_id)
            
            layer_id = self._generate_id()
            layer = InventoryLayer(
                id=layer_id,
                product_id=product_id,
                remaining_qty=quantity,
                unit_cost=avg_cost,
                created_at=transaction.timestamp,
                original_purchase_id=transaction_id,
                warehouse_id=warehouse_id
            )
            
            self.layers[layer_id] = layer
            self.layers_by_product[product_id].append(layer_id)
            adjustment_amount = -quantity * avg_cost
        
        # Store transaction
        self.transactions[transaction_id] = transaction
        self.transactions_by_product[product_id].append(transaction_id)
        
        return transaction_id, adjustment_amount
    
    def process_adjustment(self, product_id: str, quantity: float, unit_cost: float,
                         reason: str,
                         reference_id: Optional[str] = None,
                         warehouse_id: Optional[str] = None,
                         metadata: Optional[Dict] = None) -> str:
        """
        Process an inventory adjustment (write-off, correction, etc.).
        
        Args:
            product_id: Product identifier
            quantity: Quantity to adjust (positive = add, negative = remove)
            unit_cost: Cost per unit for the adjustment
            reason: Reason for adjustment
            reference_id: External reference
            warehouse_id: Optional warehouse identifier
            metadata: Additional metadata
            
        Returns:
            transaction_id
        """
        transaction_id = self._generate_id()
        
        # Create adjustment transaction
        transaction = InventoryTransaction(
            id=transaction_id,
            product_id=product_id,
            type=TransactionType.ADJUSTMENT,
            quantity=quantity,
            unit_cost=unit_cost,
            reference_id=reference_id,
            warehouse_id=warehouse_id,
            metadata={**(metadata or {}), "reason": reason}
        )
        
        if quantity > 0:
            # Adding inventory - create new layer
            layer_id = self._generate_id()
            layer = InventoryLayer(
                id=layer_id,
                product_id=product_id,
                remaining_qty=quantity,
                unit_cost=unit_cost,
                created_at=transaction.timestamp,
                original_purchase_id=transaction_id,
                warehouse_id=warehouse_id
            )
            
            self.layers[layer_id] = layer
            self.layers_by_product[product_id].append(layer_id)
            
        else:
            # Removing inventory - consume from FIFO layers
            abs_quantity = abs(quantity)
            layers = self._get_layers_fifo(product_id, warehouse_id)
            remaining = abs_quantity
            
            for layer in layers:
                if remaining <= 0:
                    break
                
                take_qty = min(layer.remaining_qty, remaining)
                layer.remaining_qty -= take_qty
                remaining -= take_qty
            
            if remaining > 0 and not self.allow_negative_inventory:
                raise InsufficientInventoryError(
                    f"Cannot adjust {abs_quantity} units. Only {abs_quantity - remaining} available."
                )
        
        # Store transaction
        self.transactions[transaction_id] = transaction
        self.transactions_by_product[product_id].append(transaction_id)
        
        return transaction_id
    
    def _get_average_cost(self, product_id: str, warehouse_id: Optional[str] = None) -> float:
        """
        Calculate weighted average cost of available inventory.
        
        Args:
            product_id: Product identifier
            warehouse_id: Optional warehouse filter
            
        Returns:
            Weighted average cost per unit
        """
        layers = self._get_layers_fifo(product_id, warehouse_id)
        
        if not layers:
            return 0.0
        
        total_qty = sum(layer.remaining_qty for layer in layers)
        total_cost = sum(layer.remaining_qty * layer.unit_cost for layer in layers)
        
        if total_qty == 0:
            return 0.0
        
        return total_cost / total_qty
    
    def get_inventory_summary(self, product_id: str, 
                            warehouse_id: Optional[str] = None) -> Dict:
        """
        Get inventory summary for a product.
        
        Args:
            product_id: Product identifier
            warehouse_id: Optional warehouse filter
            
        Returns:
            Dictionary with inventory details
        """
        layers = self._get_layers_fifo(product_id, warehouse_id)
        
        total_qty = sum(layer.remaining_qty for layer in layers)
        total_value = sum(layer.remaining_qty * layer.unit_cost for layer in layers)
        avg_cost = total_value / total_qty if total_qty > 0 else 0.0
        
        return {
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "total_quantity": total_qty,
            "total_value": total_value,
            "average_cost": avg_cost,
            "layer_count": len(layers),
            "layers": [
                {
                    "layer_id": layer.id,
                    "remaining_qty": layer.remaining_qty,
                    "unit_cost": layer.unit_cost,
                    "created_at": layer.created_at,
                    "expiry_date": layer.expiry_date
                }
                for layer in layers
            ]
        }
    
    def get_transaction_history(self, product_id: str, 
                               warehouse_id: Optional[str] = None) -> List[Dict]:
        """
        Get transaction history for a product.
        
        Args:
            product_id: Product identifier
            warehouse_id: Optional warehouse filter
            
        Returns:
            List of transaction dictionaries
        """
        transaction_ids = self.transactions_by_product.get(product_id, [])
        transactions = [self.transactions[tid] for tid in transaction_ids]
        
        # Filter by warehouse if specified
        if warehouse_id:
            transactions = [t for t in transactions if t.warehouse_id == warehouse_id]
        
        # Sort by timestamp
        transactions.sort(key=lambda x: x.timestamp)
        
        return [
            {
                "id": t.id,
                "type": t.type.value,
                "quantity": t.quantity,
                "unit_price": t.unit_price,
                "unit_cost": t.unit_cost,
                "timestamp": t.timestamp,
                "reference_id": t.reference_id,
                "metadata": t.metadata
            }
            for t in transactions
        ]
    
    def get_cogs_trace(self, sale_id: str) -> List[Dict]:
        """
        Get full COGS trace for a sale (audit trail).
        
        Args:
            sale_id: Sale transaction ID
            
        Returns:
            List of COGS entries with layer details
        """
        cogs_entries = self.cogs_by_sale.get(sale_id, [])
        
        trace = []
        for cogs in cogs_entries:
            layer = self.layers[cogs.layer_id]
            trace.append({
                "cogs_entry_id": cogs.id,
                "layer_id": cogs.layer_id,
                "quantity_taken": cogs.quantity_taken,
                "unit_cost": cogs.unit_cost,
                "total_cost": cogs.total_cost,
                "layer_details": {
                    "original_purchase_id": layer.original_purchase_id,
                    "layer_created_at": layer.created_at,
                    "original_unit_cost": layer.unit_cost
                }
            })
        
        return trace
    
    def batch_process_sales(self, sales: List[Dict]) -> List[Dict]:
        """
        Process multiple sales in batch for performance.
        
        Args:
            sales: List of sale dictionaries with keys:
                  - product_id
                  - quantity
                  - unit_price
                  - reference_id (optional)
                  - warehouse_id (optional)
                  - metadata (optional)
                  
        Returns:
            List of results with transaction_id and total_cogs
        """
        results = []
        
        for sale in sales:
            try:
                transaction_id, total_cogs = self.process_sale(
                    product_id=sale["product_id"],
                    quantity=sale["quantity"],
                    unit_price=sale["unit_price"],
                    reference_id=sale.get("reference_id"),
                    warehouse_id=sale.get("warehouse_id"),
                    metadata=sale.get("metadata")
                )
                results.append({
                    "success": True,
                    "transaction_id": transaction_id,
                    "total_cogs": total_cogs,
                    "error": None
                })
            except Exception as e:
                results.append({
                    "success": False,
                    "transaction_id": None,
                    "total_cogs": None,
                    "error": str(e)
                })
        
        return results


def example_walkthrough():
    """
    Example walkthrough demonstrating the FIFO COGS system.
    """
    print("=" * 80)
    print("FIFO COGS SYSTEM - EXAMPLE WALKTHROUGH")
    print("=" * 80)
    
    # Initialize system
    system = FIFOInventorySystem(allow_negative_inventory=False)
    
    # Product: Widget A
    product_id = "WIDGET-A"
    
    print("\n1. INITIAL PURCHASES")
    print("-" * 80)
    
    # Purchase 1: 100 units at $10.00
    t1_id, l1_id = system.record_purchase(
        product_id=product_id,
        quantity=100,
        unit_cost=10.00,
        reference_id="PO-001"
    )
    print(f"Purchase 1: 100 units @ $10.00 (Layer: {l1_id[:8]}...)")
    
    # Purchase 2: 150 units at $12.00
    t2_id, l2_id = system.record_purchase(
        product_id=product_id,
        quantity=150,
        unit_cost=12.00,
        reference_id="PO-002"
    )
    print(f"Purchase 2: 150 units @ $12.00 (Layer: {l2_id[:8]}...)")
    
    # Purchase 3: 200 units at $11.00
    t3_id, l3_id = system.record_purchase(
        product_id=product_id,
        quantity=200,
        unit_cost=11.00,
        reference_id="PO-003"
    )
    print(f"Purchase 3: 200 units @ $11.00 (Layer: {l3_id[:8]}...)")
    
    print("\nInventory Summary:")
    summary = system.get_inventory_summary(product_id)
    print(f"  Total Quantity: {summary['total_quantity']}")
    print(f"  Total Value: ${summary['total_value']:.2f}")
    print(f"  Average Cost: ${summary['average_cost']:.2f}")
    print(f"  Layers: {summary['layer_count']}")
    
    print("\n2. FIRST SALE - 120 units")
    print("-" * 80)
    
    # Sale 1: 120 units at $20.00
    sale1_id, cogs1 = system.process_sale(
        product_id=product_id,
        quantity=120,
        unit_price=20.00,
        reference_id="SO-001"
    )
    print(f"Sale 1: 120 units @ $20.00 selling price")
    print(f"  COGS Calculation:")
    print(f"    - From Layer 1 (100 units @ $10.00): $1,000.00")
    print(f"    - From Layer 2 (20 units @ $12.00): $240.00")
    print(f"  Total COGS: ${cogs1:.2f}")
    print(f"  Gross Profit: ${120 * 20.00 - cogs1:.2f}")
    
    print("\nInventory Summary after Sale 1:")
    summary = system.get_inventory_summary(product_id)
    print(f"  Total Quantity: {summary['total_quantity']}")
    print(f"  Total Value: ${summary['total_value']:.2f}")
    
    print("\n3. SECOND SALE - 180 units")
    print("-" * 80)
    
    # Sale 2: 180 units at $20.00
    sale2_id, cogs2 = system.process_sale(
        product_id=product_id,
        quantity=180,
        unit_price=20.00,
        reference_id="SO-002"
    )
    print(f"Sale 2: 180 units @ $20.00 selling price")
    print(f"  COGS Calculation:")
    print(f"    - From Layer 2 (130 units @ $12.00): $1,560.00")
    print(f"    - From Layer 3 (50 units @ $11.00): $550.00")
    print(f"  Total COGS: ${cogs2:.2f}")
    print(f"  Gross Profit: ${180 * 20.00 - cogs2:.2f}")
    
    print("\nInventory Summary after Sale 2:")
    summary = system.get_inventory_summary(product_id)
    print(f"  Total Quantity: {summary['total_quantity']}")
    print(f"  Total Value: ${summary['total_value']:.2f}")
    
    print("\n4. COGS TRACE FOR SALE 1")
    print("-" * 80)
    trace = system.get_cogs_trace(sale1_id)
    for entry in trace:
        print(f"  Layer {entry['layer_id'][:8]}...:")
        print(f"    Quantity Taken: {entry['quantity_taken']}")
        print(f"    Unit Cost: ${entry['unit_cost']:.2f}")
        print(f"    Total Cost: ${entry['total_cost']:.2f}")
    
    print("\n5. RETURN - 30 units from Sale 1")
    print("-" * 80)
    
    # Return 30 units
    return_id, adjustment = system.process_return(
        product_id=product_id,
        quantity=30,
        original_sale_id=sale1_id,
        reference_id="RMA-001"
    )
    print(f"Return: 30 units from Sale 1")
    print(f"  Adjustment Amount: ${adjustment:.2f} (reduces COGS)")
    
    print("\nInventory Summary after Return:")
    summary = system.get_inventory_summary(product_id)
    print(f"  Total Quantity: {summary['total_quantity']}")
    print(f"  Total Value: ${summary['total_value']:.2f}")
    
    print("\n6. INVENTORY ADJUSTMENT - Write-off 10 units")
    print("-" * 80)
    
    # Adjustment: Write-off 10 damaged units
    adj_id = system.process_adjustment(
        product_id=product_id,
        quantity=-10,
        unit_cost=11.00,
        reason="Damaged goods write-off",
        reference_id="ADJ-001"
    )
    print(f"Adjustment: -10 units (Damaged goods write-off)")
    
    print("\nFinal Inventory Summary:")
    summary = system.get_inventory_summary(product_id)
    print(f"  Total Quantity: {summary['total_quantity']}")
    print(f"  Total Value: ${summary['total_value']:.2f}")
    print(f"  Average Cost: ${summary['average_cost']:.2f}")
    
    print("\n7. TRANSACTION HISTORY")
    print("-" * 80)
    history = system.get_transaction_history(product_id)
    for tx in history:
        print(f"  {tx['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} - "
              f"{tx['type']:12} | Qty: {tx['quantity']:6.0f} | "
              f"Cost: ${tx['unit_cost'] or 0:6.2f} | Ref: {tx['reference_id'] or 'N/A'}")
    
    print("\n" + "=" * 80)
    print("WALKTHROUGH COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    example_walkthrough()
