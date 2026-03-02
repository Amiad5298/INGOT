# Implementation Plan: RED-126866

## Summary
Add alerting for high message count in SQS and PubSub queues.

## Technical Approach
Use Micrometer Gauge to track pending message counts and configure alerting thresholds.

## Implementation Steps
1. **File**: `src/main/java/com/example/MonitorService.java`
   Add a Gauge metric for pending messages.
   Pattern source: `src/main/java/com/example/MetricsHelper.java:43-59`
```java
Gauge.builder("queue.pending.messages", () -> getPendingCount())
    .register(meterRegistry);
```

<!-- NOTE: Missing Testing Strategy, Potential Risks, and Out of Scope sections -->
