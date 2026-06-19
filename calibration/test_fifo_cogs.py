"""
Comprehensive Test Suite for FIFO COGS System

Tests cover:
- Simple FIFO consumption
- Multi-layer depletion
- Large volume transactions
- Edge cases (returns, zero inventory, partial consumption)
- Auditability and traceability
- Performance considerations
"""

import unittest
from datetime import datetime, timedelta
from fifo_cogs_system import (
    FIFOInventorySystem,
    TransactionType,
    ReturnPolicy,
    InsufficientInventoryError,
    InventoryLayer,
    InventoryTransaction,
    COGSEntry
)


class TestFIFOInventorySystem(unittest.TestCase):
    """Test cases for FIFO inventory management system"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.system = FIFOInventorySystem(allow_negative_inventory=False)
        self.product_id = "TEST-PRODUCT-001"
    
    def test_simple_purchase(self):
        """Test basic purchase transaction"""
        tx_id, layer_id = self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00,
            reference_id="PO-TEST-001"
        )
        
        # Verify transaction created
        self.assertIn(tx_id, self.system.transactions)
        transaction = self.system.transactions[tx_id]
        self.assertEqual(transaction.type, TransactionType.PURCHASE)
        self.assertEqual(transaction.quantity, 100)
        self.assertEqual(transaction.unit_cost, 10.00)
        
        # Verify layer created
        self.assertIn(layer_id, self.system.layers)
        layer = self.system.layers[layer_id]
        self.assertEqual(layer.remaining_qty, 100)
        self.assertEqual(layer.unit_cost, 10.00)
    
    def test_simple_fifo_consumption(self):
        """Test basic FIFO consumption - single layer"""
        # Purchase 100 units at $10
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        
        # Sell 50 units
        sale_id, cogs = self.system.process_sale(
            product_id=self.product_id,
            quantity=50,
            unit_price=20.00
        )
        
        # Verify COGS calculation
        self.assertEqual(cogs, 500.00)  # 50 * $10
        
        # Verify remaining inventory
        summary = self.system.get_inventory_summary(self.product_id)
        self.assertEqual(summary['total_quantity'], 50)
        self.assertEqual(summary['total_value'], 500.00)
    
    def test_multi_layer_fifo_consumption(self):
        """Test FIFO consumption across multiple layers"""
        # Purchase at different costs
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=150,
            unit_cost=12.00
        )
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=200,
            unit_cost=11.00
        )
        
        # Sell 250 units
        sale_id, cogs = self.system.process_sale(
            product_id=self.product_id,
            quantity=250,
            unit_price=20.00
        )
        
        # Expected COGS:
        # - 100 units from first layer @ $10 = $1,000
        # - 150 units from second layer @ $12 = $1,800
        # Total = $2,800
        self.assertEqual(cogs, 2800.00)
        
        # Verify remaining inventory (only third layer should have 200 left)
        summary = self.system.get_inventory_summary(self.product_id)
        self.assertEqual(summary['total_quantity'], 200)
        self.assertEqual(summary['total_value'], 2200.00)  # 200 * $11
    
    def test_partial_layer_consumption(self):
        """Test consumption that partially depletes a layer"""
        # Purchase 100 units at $10
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        
        # Sell 30 units
        sale_id, cogs = self.system.process_sale(
            product_id=self.product_id,
            quantity=30,
            unit_price=20.00
        )
        
        # Verify layer has 70 remaining
        layers = self.system._get_layers_fifo(self.product_id)
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0].remaining_qty, 70)
        self.assertEqual(cogs, 300.00)
    
    def test_insufficient_inventory_error(self):
        """Test error when selling more than available"""
        # Purchase only 50 units
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=50,
            unit_cost=10.00
        )
        
        # Try to sell 100 units
        with self.assertRaises(InsufficientInventoryError):
            self.system.process_sale(
                product_id=self.product_id,
                quantity=100,
                unit_price=20.00
            )
    
    def test_insufficient_inventory_with_allow_negative(self):
        """Test that negative inventory is allowed when configured"""
        system = FIFOInventorySystem(allow_negative_inventory=True)
        
        # Purchase 50 units
        system.record_purchase(
            product_id=self.product_id,
            quantity=50,
            unit_cost=10.00
        )
        
        # Sell 100 units (should succeed)
        sale_id, cogs = system.process_sale(
            product_id=self.product_id,
            quantity=100,
            unit_price=20.00
        )
        
        self.assertEqual(cogs, 500.00)  # Only 50 units available
    
    def test_return_restore_original_layer(self):
        """Test return with restore to original layer policy"""
        system = FIFOInventorySystem(
            allow_negative_inventory=False,
            return_policy=ReturnPolicy.RESTORE_ORIGINAL_LAYER
        )
        
        # Purchase 100 units at $10
        system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        
        # Sell 50 units
        sale_id, cogs = system.process_sale(
            product_id=self.product_id,
            quantity=50,
            unit_price=20.00
        )
        
        # Return 20 units
        return_id, adjustment = system.process_return(
            product_id=self.product_id,
            quantity=20,
            original_sale_id=sale_id
        )
        
        # Verify inventory restored
        summary = system.get_inventory_summary(self.product_id)
        self.assertEqual(summary['total_quantity'], 70)  # 50 remaining + 20 returned
        
        # Verify adjustment reduces COGS
        self.assertEqual(adjustment, -200.00)  # -20 * $10
    
    def test_return_create_new_layer(self):
        """Test return with create new layer policy"""
        system = FIFOInventorySystem(
            allow_negative_inventory=False,
            return_policy=ReturnPolicy.CREATE_NEW_LAYER
        )
        
        # Purchase 100 units at $10
        system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        
        # Sell 50 units
        sale_id, cogs = system.process_sale(
            product_id=self.product_id,
            quantity=50,
            unit_price=20.00
        )
        
        # Return 20 units
        return_id, adjustment = system.process_return(
            product_id=self.product_id,
            quantity=20,
            original_sale_id=sale_id
        )
        
        # Verify new layer created
        summary = system.get_inventory_summary(self.product_id)
        self.assertEqual(summary['total_quantity'], 70)
        self.assertEqual(summary['layer_count'], 2)  # Original + new return layer
    
    def test_inventory_adjustment_add(self):
        """Test inventory adjustment adding stock"""
        # Add 50 units via adjustment
        adj_id = self.system.process_adjustment(
            product_id=self.product_id,
            quantity=50,
            unit_cost=15.00,
            reason="Stock correction"
        )
        
        summary = self.system.get_inventory_summary(self.product_id)
        self.assertEqual(summary['total_quantity'], 50)
        self.assertEqual(summary['total_value'], 750.00)
    
    def test_inventory_adjustment_remove(self):
        """Test inventory adjustment removing stock"""
        # Purchase 100 units
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        
        # Remove 30 units via adjustment
        adj_id = self.system.process_adjustment(
            product_id=self.product_id,
            quantity=-30,
            unit_cost=10.00,
            reason="Damaged goods"
        )
        
        summary = self.system.get_inventory_summary(self.product_id)
        self.assertEqual(summary['total_quantity'], 70)
    
    def test_zero_inventory_sale(self):
        """Test sale when inventory is zero"""
        with self.assertRaises(InsufficientInventoryError):
            self.system.process_sale(
                product_id=self.product_id,
                quantity=10,
                unit_price=20.00
            )
    
    def test_cogs_trace(self):
        """Test COGS traceability"""
        # Purchase multiple layers
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=150,
            unit_cost=12.00
        )
        
        # Sell
        sale_id, cogs = self.system.process_sale(
            product_id=self.product_id,
            quantity=120,
            unit_price=20.00
        )
        
        # Get trace
        trace = self.system.get_cogs_trace(sale_id)
        
        # Should have 2 entries (one from each layer)
        self.assertEqual(len(trace), 2)
        
        # First entry should be from first layer (100 units)
        self.assertEqual(trace[0]['quantity_taken'], 100)
        self.assertEqual(trace[0]['unit_cost'], 10.00)
        
        # Second entry should be from second layer (20 units)
        self.assertEqual(trace[1]['quantity_taken'], 20)
        self.assertEqual(trace[1]['unit_cost'], 12.00)
    
    def test_transaction_history(self):
        """Test transaction history retrieval"""
        # Record multiple transactions
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00,
            reference_id="PO-001"
        )
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=50,
            unit_cost=12.00,
            reference_id="PO-002"
        )
        
        history = self.system.get_transaction_history(self.product_id)
        
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['reference_id'], "PO-001")
        self.assertEqual(history[1]['reference_id'], "PO-002")
    
    def test_warehouse_filtering(self):
        """Test warehouse-specific inventory tracking"""
        warehouse_a = "WAREHOUSE-A"
        warehouse_b = "WAREHOUSE-B"
        
        # Purchase in warehouse A
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00,
            warehouse_id=warehouse_a
        )
        
        # Purchase in warehouse B
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=50,
            unit_cost=12.00,
            warehouse_id=warehouse_b
        )
        
        # Check warehouse A
        summary_a = self.system.get_inventory_summary(
            self.product_id,
            warehouse_id=warehouse_a
        )
        self.assertEqual(summary_a['total_quantity'], 100)
        
        # Check warehouse B
        summary_b = self.system.get_inventory_summary(
            self.product_id,
            warehouse_id=warehouse_b
        )
        self.assertEqual(summary_b['total_quantity'], 50)
        
        # Check total
        summary_total = self.system.get_inventory_summary(self.product_id)
        self.assertEqual(summary_total['total_quantity'], 150)
    
    def test_expiry_date_fefo(self):
        """Test First-Expired-First-Out (FEFO) with expiry dates"""
        now = datetime.utcnow()
        
        # Purchase with later expiry
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00,
            expiry_date=now + timedelta(days=30)
        )
        
        # Purchase with earlier expiry
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=12.00,
            expiry_date=now + timedelta(days=10)
        )
        
        # Sell 50 units - should consume from earlier expiry first
        sale_id, cogs = self.system.process_sale(
            product_id=self.product_id,
            quantity=50,
            unit_price=20.00
        )
        
        # Should consume from $12 layer (earlier expiry)
        self.assertEqual(cogs, 600.00)  # 50 * $12
    
    def test_batch_processing(self):
        """Test batch processing of multiple sales"""
        # Setup inventory
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=500,
            unit_cost=10.00
        )
        
        # Prepare batch sales
        sales = [
            {"product_id": self.product_id, "quantity": 100, "unit_price": 20.00},
            {"product_id": self.product_id, "quantity": 150, "unit_price": 20.00},
            {"product_id": self.product_id, "quantity": 200, "unit_price": 20.00},
        ]
        
        # Process batch
        results = self.system.batch_process_sales(sales)
        
        # Verify all succeeded
        self.assertEqual(len(results), 3)
        for result in results:
            self.assertTrue(result['success'])
            self.assertIsNotNone(result['transaction_id'])
        
        # Verify total inventory
        summary = self.system.get_inventory_summary(self.product_id)
        self.assertEqual(summary['total_quantity'], 50)  # 500 - 450
    
    def test_batch_processing_with_errors(self):
        """Test batch processing with some failures"""
        # Setup limited inventory
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        
        # Prepare batch with insufficient inventory
        sales = [
            {"product_id": self.product_id, "quantity": 50, "unit_price": 20.00},
            {"product_id": self.product_id, "quantity": 100, "unit_price": 20.00},  # Will fail
            {"product_id": self.product_id, "quantity": 20, "unit_price": 20.00},
        ]
        
        # Process batch
        results = self.system.batch_process_sales(sales)
        
        # First should succeed
        self.assertTrue(results[0]['success'])
        
        # Second should fail
        self.assertFalse(results[1]['success'])
        self.assertIn("Insufficient", results[1]['error'])
        
        # Third should succeed (50 units still available after first sale)
        self.assertTrue(results[2]['success'])
    
    def test_average_cost_calculation(self):
        """Test weighted average cost calculation"""
        # Purchase at different costs
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=20.00
        )
        
        avg_cost = self.system._get_average_cost(self.product_id)
        
        # (100*10 + 100*20) / 200 = 15
        self.assertEqual(avg_cost, 15.00)
    
    def test_layer_depletion(self):
        """Test that depleted layers are handled correctly"""
        # Purchase
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00
        )
        
        # Sell all
        sale_id, cogs = self.system.process_sale(
            product_id=self.product_id,
            quantity=100,
            unit_price=20.00
        )
        
        # Get layers - should return empty (all depleted)
        layers = self.system._get_layers_fifo(self.product_id)
        self.assertEqual(len(layers), 0)
    
    def test_complex_scenario(self):
        """Test a complex real-world scenario"""
        # Day 1: Purchase 100 @ $10
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=100,
            unit_cost=10.00,
            reference_id="PO-DAY1"
        )
        
        # Day 2: Sell 30 @ $20
        sale1_id, cogs1 = self.system.process_sale(
            product_id=self.product_id,
            quantity=30,
            unit_price=20.00,
            reference_id="SO-DAY2"
        )
        self.assertEqual(cogs1, 300.00)
        
        # Day 3: Purchase 50 @ $15
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=50,
            unit_cost=15.00,
            reference_id="PO-DAY3"
        )
        
        # Day 4: Sell 80 @ $20
        sale2_id, cogs2 = self.system.process_sale(
            product_id=self.product_id,
            quantity=80,
            unit_price=20.00,
            reference_id="SO-DAY4"
        )
        # Expected: 70 from first layer @ $10 + 10 from second @ $15
        # = 700 + 150 = 850
        self.assertEqual(cogs2, 850.00)
        
        # Day 5: Return 10 from sale2
        return_id, adj = self.system.process_return(
            product_id=self.product_id,
            quantity=10,
            original_sale_id=sale2_id,
            reference_id="RMA-DAY5"
        )
        
        # Final inventory check
        summary = self.system.get_inventory_summary(self.product_id)
        # Started with 150, sold 110, returned 10 = 50
        self.assertEqual(summary['total_quantity'], 50)
    
    def test_large_volume_performance(self):
        """Test performance with large volume transactions"""
        # Purchase 10,000 units
        self.system.record_purchase(
            product_id=self.product_id,
            quantity=10000,
            unit_cost=10.00
        )
        
        # Sell in multiple batches
        total_cogs = 0
        for i in range(100):
            sale_id, cogs = self.system.process_sale(
                product_id=self.product_id,
                quantity=100,
                unit_price=20.00
            )
            total_cogs += cogs
        
        # Verify total
        self.assertEqual(total_cogs, 100000.00)  # 10,000 * $10
        
        summary = self.system.get_inventory_summary(self.product_id)
        self.assertEqual(summary['total_quantity'], 0)


class TestDataModels(unittest.TestCase):
    """Test data model validation"""
    
    def test_inventory_layer_validation(self):
        """Test InventoryLayer validation"""
        with self.assertRaises(ValueError):
            InventoryLayer(
                id="test",
                product_id="PROD-001",
                remaining_qty=-10,  # Invalid
                unit_cost=10.00,
                created_at=datetime.utcnow(),
                original_purchase_id="PO-001"
            )
        
        with self.assertRaises(ValueError):
            InventoryLayer(
                id="test",
                product_id="PROD-001",
                remaining_qty=10,
                unit_cost=-5.00,  # Invalid
                created_at=datetime.utcnow(),
                original_purchase_id="PO-001"
            )
    
    def test_transaction_validation(self):
        """Test InventoryTransaction validation"""
        with self.assertRaises(ValueError):
            InventoryTransaction(
                id="test",
                product_id="PROD-001",
                type=TransactionType.PURCHASE,
                quantity=-10,  # Invalid for purchase
                unit_cost=10.00
            )
        
        with self.assertRaises(ValueError):
            InventoryTransaction(
                id="test",
                product_id="PROD-001",
                type=TransactionType.SALE,
                quantity=-10,  # Invalid for sale
                unit_price=20.00
            )


def run_tests():
    """Run all tests"""
    unittest.main(argv=[''], verbosity=2, exit=False)


if __name__ == "__main__":
    run_tests()
