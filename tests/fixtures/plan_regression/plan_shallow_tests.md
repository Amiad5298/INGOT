# Implementation Plan: RED-188772-F3

## Summary
Add an event listener that sends a notification email when a
`GuardEvaluatedEvent` is emitted with a negative result.

## Technical Approach
Create a Spring `@EventListener` that listens for `GuardEvaluatedEvent`
and dispatches email notifications via the existing `NotificationService`.

## Implementation Steps
1. **File**: `src/main/java/com/example/listeners/GuardFailureNotifier.java` <!-- NEW_FILE -->
   Create event listener for guard failure notifications.
   <!-- NO_EXISTING_PATTERN: first event listener in project -->
```java
@Component
public class GuardFailureNotifier {
    private final NotificationService notificationService;

    public GuardFailureNotifier(NotificationService notificationService) {
        this.notificationService = notificationService;
    }

    @EventListener
    public void onGuardEvaluated(GuardEvaluatedEvent event) {
        if (!event.isResult()) {
            notificationService.sendEmail(
                "Guard Failed",
                "Guard " + event.getGuardName() + " evaluated to false"
            );
        }
    }
}
```

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `GuardFailureNotifier.java` | `src/test/java/com/example/listeners/GuardFailureNotifierTest.java` | basic test |

## Potential Risks or Considerations
- **External dependencies**: Email service availability
- **Prerequisite work**: None identified
- **Data integrity / state management**: None identified
- **Startup / cold-start behavior**: None identified
- **Environment / configuration drift**: Email configuration required
- **Performance / scalability**: Email sending is async
- **Backward compatibility**: New listener, no existing behavior changed

## Out of Scope
- Email template customization
- Notification preferences
