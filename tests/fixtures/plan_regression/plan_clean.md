# Implementation Plan: CLEAN-100

## Summary
Add a REST endpoint to return user profile data from the existing `UserService`.

## Technical Approach
Use Spring MVC `@RestController` with the existing `UserService` bean. Follow the
established controller pattern from `OrderController`.

## Implementation Steps
1. **File**: `src/main/java/com/example/UserProfileController.java`
   Create a new REST controller that delegates to `UserService`.
   Pattern source: `src/main/java/com/example/OrderController.java:12-30`
```java
@RestController
@RequestMapping("/api/v1/users")
public class UserProfileController {
    private final UserService userService;

    public UserProfileController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping("/{userId}/profile")
    public ResponseEntity<UserProfile> getProfile(@PathVariable String userId) {
        return ResponseEntity.ok(userService.getProfile(userId));
    }
}
```

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `UserProfileController.java` | `src/test/java/com/example/UserProfileControllerTest.java` | happy path, user not found, invalid ID |

## Potential Risks or Considerations
- **External dependencies**: None identified
- **Prerequisite work**: None identified
- **Data integrity / state management**: None identified
- **Startup / cold-start behavior**: None identified
- **Environment / configuration drift**: None identified
- **Performance / scalability**: Delegates to existing cached `UserService`
- **Backward compatibility**: New endpoint, no existing contracts affected

## Out of Scope
- Profile update (PUT/PATCH) endpoint
- Profile image upload
