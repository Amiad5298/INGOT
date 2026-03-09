# Implementation Plan: CLEAN-200

## Summary
Add a REST endpoint to return user profile data and emit a `ProfileViewedEvent`
when the profile is accessed.  Downstream, the analytics handler records the view.

## Technical Approach
Use Spring MVC `@RestController` with the existing `UserService` bean. Follow the
established controller pattern from `OrderController`. The `ProfileViewedEvent` will
be consumed by the existing `AnalyticsEventHandler` which records view counts — this
is a downstream consumer that triggers no user-visible side effects.

## Implementation Steps
1. **File**: `src/main/java/com/example/UserProfileController.java` <!-- NEW_FILE -->
   Create a new REST controller that delegates to `UserService`.
   All controllers in `ControllerRegistry` are wrapped with `metricsInterceptor.wrap(...)`.
   Pattern source: `src/main/java/com/example/OrderController.java:12-30`
```java
@RestController
@RequestMapping("/api/v1/users")
public class UserProfileController {
    private final UserService userService;
    private final ApplicationEventPublisher eventPublisher;

    public UserProfileController(UserService userService, ApplicationEventPublisher eventPublisher) {
        this.userService = userService;
        this.eventPublisher = eventPublisher;
    }

    @GetMapping("/{userId}/profile")
    public ResponseEntity<UserProfile> getProfile(@PathVariable String userId) {
        UserProfile profile = userService.getProfile(userId);
        eventPublisher.publishEvent(new ProfileViewedEvent(userId));
        return ResponseEntity.ok(profile);
    }
}
```

2. **File**: `src/main/java/com/example/config/ControllerRegistry.java`
   Register the new controller with the metrics interceptor wrapper, consistent
   with the existing pattern applied to all sibling controllers.
   Pattern source: `src/main/java/com/example/config/ControllerRegistry.java:20-35`
```java
// All controllers are wrapped with metricsInterceptor:
registry.register(metricsInterceptor.wrap(orderController));
registry.register(metricsInterceptor.wrap(paymentController));
// Add new controller with same wrapping:
registry.register(metricsInterceptor.wrap(userProfileController));
```

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `UserProfileController.java` | `src/test/java/com/example/UserProfileControllerTest.java` | verify happy path returns profile, verify user not found returns 404, verify event emitted on access, verify invalid userId returns 400 |
| `ControllerRegistry.java` | `src/test/java/com/example/config/ControllerRegistryTest.java` | verify controller registered, verify metrics interceptor applied, verify all controllers wrapped |

## Potential Risks or Considerations
- **External dependencies**: None identified
- **Prerequisite work**: None identified
- **Data integrity / state management**: Read-only endpoint, no mutation risk
- **Startup / cold-start behavior**: None identified
- **Environment / configuration drift**: None identified
- **Performance / scalability**: Delegates to existing cached `UserService`; event publishing is synchronous but lightweight
- **Backward compatibility**: New endpoint, no existing contracts affected
- **Idempotency / duplicate handling**: `ProfileViewedEvent` is idempotent — duplicate views are recorded as separate counts, which is the intended behavior
- **Downstream consumer impact**: `AnalyticsEventHandler` consumes `ProfileViewedEvent` and increments a counter; no user-visible notification is triggered

## Out of Scope
- Profile update (PUT/PATCH) endpoint
- Profile image upload
- Async event processing
