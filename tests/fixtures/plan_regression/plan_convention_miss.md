# Implementation Plan: RED-188772-F2

## Summary
Add a new `CancelOrderAction` to the order state machine configuration,
triggered when an order transitions to the CANCELLED state.

## Technical Approach
Follow the existing action pattern from `ShipOrderAction` and `RefundOrderAction`
in the `OrderStateMachineConfig` class.

## Implementation Steps
1. **File**: `src/main/java/com/example/actions/CancelOrderAction.java` <!-- NEW_FILE -->
   Create a new action that handles order cancellation logic.
   Pattern source: `src/main/java/com/example/actions/ShipOrderAction.java:10-35`
```java
@Component
public class CancelOrderAction implements Action<OrderState, OrderEvent> {
    private final OrderService orderService;

    public CancelOrderAction(OrderService orderService) {
        this.orderService = orderService;
    }

    @Override
    public void execute(StateContext<OrderState, OrderEvent> context) {
        String orderId = context.getMessageHeader("orderId", String.class);
        orderService.cancelOrder(orderId);
    }
}
```

2. **File**: `src/main/java/com/example/config/OrderStateMachineConfig.java`
   Register the new action in the state machine configuration.
   Pattern source: `src/main/java/com/example/config/OrderStateMachineConfig.java:45-60`
```java
// Existing actions are all wrapped with metricsDecorator:
// .action(metricsDecorator.wrap(shipOrderAction))
// .action(metricsDecorator.wrap(refundOrderAction))
// New action registration:
.action(cancelOrderAction)
```

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `CancelOrderAction.java` | `src/test/java/com/example/actions/CancelOrderActionTest.java` | verify cancel called, verify error on missing orderId, verify idempotent cancel |
| `OrderStateMachineConfig.java` | `src/test/java/com/example/config/OrderStateMachineConfigTest.java` | verify action registered, verify transition triggers action, verify metrics recorded |

## Potential Risks or Considerations
- **External dependencies**: None identified
- **Prerequisite work**: None identified
- **Data integrity / state management**: Cancellation must be idempotent
- **Startup / cold-start behavior**: None identified
- **Environment / configuration drift**: None identified
- **Performance / scalability**: None identified
- **Backward compatibility**: New action, no existing behavior changed

## Out of Scope
- Notification to customer on cancellation
- Refund trigger from cancellation
