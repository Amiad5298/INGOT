# Implementation Plan: RED-188772-F6

## Summary
Emit a `GuardEvaluatedEvent` from the order guard to decouple the
notification logic from the guard evaluation.

## Technical Approach
Use Spring's event publisher to emit an event after guard evaluation.
This decouples the guard from direct notification calls.

## Implementation Steps
1. **File**: `src/main/java/com/example/guards/OrderGuard.java`
   Refactor guard to publish event instead of directly sending notification email.
   Pattern source: `src/main/java/com/example/guards/PaymentGuard.java:15-30`
```java
@Override
public boolean evaluate(StateContext context) {
    boolean result = orderService.isValid(context.getOrderId());
    // Emit event instead of calling notificationService directly
    eventPublisher.publishEvent(new GuardEvaluatedEvent("OrderGuard", result, context));
    return result;
}
```

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `OrderGuard.java` | `src/test/java/com/example/guards/OrderGuardTest.java` | verify event emitted on true, verify event emitted on false, verify no direct notification call |

## Potential Risks or Considerations
- **External dependencies**: Spring event infrastructure
- **Prerequisite work**: None identified
- **Data integrity / state management**: Event must carry full context
- **Startup / cold-start behavior**: None identified
- **Environment / configuration drift**: None identified
- **Performance / scalability**: Synchronous event delivery adds minimal overhead
- **Backward compatibility**: Notification behavior unchanged from user perspective

## Out of Scope
- Async event processing
- Event replay
