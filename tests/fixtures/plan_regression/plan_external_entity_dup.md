# Implementation Plan: RED-188772-F1

## Summary
Refactor the state machine guard to emit a `GuardEvaluatedEvent` when
the guard condition is checked, decoupling the side effect from the guard.

## Technical Approach
Create a new `GuardEvaluatedEvent` class and emit it from the refactored
guard.  The event will carry the guard result and the transition context.

## Implementation Steps
1. **File**: `src/main/java/com/example/events/GuardEvaluatedEvent.java` <!-- NEW_FILE -->
   Create a new event class to represent guard evaluation results.
```java
public class GuardEvaluatedEvent {
    private final String guardName;
    private final boolean result;
    private final TransitionContext context;

    public GuardEvaluatedEvent(String guardName, boolean result, TransitionContext context) {
        this.guardName = guardName;
        this.result = result;
        this.context = context;
    }
}
```

2. **File**: `src/main/java/com/example/guards/OrderGuard.java`
   Refactor the guard to emit `GuardEvaluatedEvent` instead of performing
   side effects directly.
   Pattern source: `src/main/java/com/example/guards/PaymentGuard.java:15-30`
```java
@Override
public boolean evaluate(StateContext context) {
    boolean result = orderService.isValid(context.getOrderId());
    eventPublisher.publishEvent(new GuardEvaluatedEvent("OrderGuard", result, context));
    return result;
}
```

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `GuardEvaluatedEvent.java` | `src/test/java/com/example/events/GuardEvaluatedEventTest.java` | verify event created, verify payload, verify serialization |
| `OrderGuard.java` | `src/test/java/com/example/guards/OrderGuardTest.java` | verify event emitted on true, verify event emitted on false, verify no side effects in guard |

## Potential Risks or Considerations
- **External dependencies**: None identified
- **Prerequisite work**: None identified
- **Data integrity / state management**: Event must carry complete context
- **Startup / cold-start behavior**: None identified
- **Environment / configuration drift**: None identified
- **Performance / scalability**: Event publishing is async, no impact
- **Backward compatibility**: Guard interface unchanged

## Out of Scope
- Downstream event handlers
- Event persistence
