# Implementation Plan: RED-127000

## Summary
Add a new SQS message consumer service for marketplace events.

## Technical Approach
Create a Spring-managed service that consumes SQS messages.

## Implementation Steps
1. **File**: `src/main/java/com/example/SqsConsumer.java`
   Create the SQS consumer service and register it as a bean.
   Pattern source: `src/main/java/com/example/ExistingConsumer.java:10-30`
```java
@Component
public class SqsConsumer {
    private final MessageProcessor processor;
    private final MetricsHelper metricsHelper;

    public SqsConsumer(MessageProcessor processor, MetricsHelper metricsHelper) {
        this.processor = processor;
        this.metricsHelper = metricsHelper;
    }
}

// Also register via explicit @Bean method in the same config
@Bean
public SqsConsumer sqsConsumer(MessageProcessor processor, MetricsHelper helper) {
    return new SqsConsumer(processor, helper);
}
```

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `SqsConsumer.java` | `src/test/java/com/example/SqsConsumerTest.java` | message processing, error handling |

## Potential Risks or Considerations
- **External dependencies**: None identified
- **Prerequisite work**: None identified
- **Data integrity / state management**: None identified
- **Startup / cold-start behavior**: None identified
- **Environment / configuration drift**: None identified
- **Performance / scalability**: None identified
- **Backward compatibility**: None identified

## Out of Scope
- GCP PubSub integration (separate ticket)
