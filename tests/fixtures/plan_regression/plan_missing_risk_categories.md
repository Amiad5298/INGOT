# Implementation Plan: RED-188772-F4

## Summary
Refactor the order guard to emit a `GuardEvaluatedEvent` via the
application event publisher, removing side effects from the guard.

## Technical Approach
Use Spring's `ApplicationEventPublisher` to emit an event from the guard.
The state machine transition ordering remains unchanged.

## Implementation Steps
1. **File**: `src/main/java/com/example/guards/OrderGuard.java`
   Emit event from guard after evaluation.
   Pattern source: `src/main/java/com/example/guards/PaymentGuard.java:15-30`
```java
@Override
public boolean evaluate(StateContext context) {
    boolean result = orderService.isValid(context.getOrderId());
    eventPublisher.publishEvent(new GuardEvaluatedEvent("OrderGuard", result, context));
    return result;
}
```

2. **File**: `src/main/java/com/example/config/StateMachineConfig.java`
   Wire the event publisher into the guard via constructor injection.
   Pattern source: `src/main/java/com/example/config/StateMachineConfig.java:20-40`
```java
@Bean
public Guard<OrderState, OrderEvent> orderGuard(
        OrderService orderService,
        ApplicationEventPublisher eventPublisher) {
    return new OrderGuard(orderService, eventPublisher);
}
```

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `OrderGuard.java` | `src/test/java/com/example/guards/OrderGuardTest.java` | verify event emitted, verify guard returns correct result, verify error handling |

## Potential Risks or Considerations
- **External dependencies**: Spring event publisher
- **Prerequisite work**: None identified
- **Performance / scalability**: Synchronous event publishing may add latency

## Out of Scope
- Async event processing
- Event persistence
