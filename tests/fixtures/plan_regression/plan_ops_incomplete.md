# Implementation Plan: RED-126866

## Summary
Add Prometheus gauge metric for monitoring pending message count in SQS and
PubSub queues. Configure alerting when queue depth exceeds thresholds.

## Technical Approach
Use Micrometer Gauge to expose queue depth as a Prometheus metric. The metric
will be scraped by our existing Prometheus setup.

## Implementation Steps
1. **File**: `src/main/java/com/example/QueueDepthGauge.java`
   Create gauge metric for pending messages.
   Pattern source: `src/main/java/com/example/StuckAccountMonitor.java:45-60`
```java
@Component
public class QueueDepthGauge {
    @Autowired
    private MeterRegistry registry;
    private final AtomicInteger pendingCount = new AtomicInteger(0);

    @PostConstruct
    public void init() {
        Gauge.builder("marketplace.queue.pending", pendingCount, AtomicInteger::get)
            .tag("queue", queueName)
            .register(registry);
    }
}
```

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `QueueDepthGauge.java` | `src/test/java/com/example/QueueDepthGaugeTest.java` | gauge registration, value update |

## Potential Risks or Considerations
- **External dependencies**: None identified
- **Prerequisite work**: None identified
- **Data integrity / state management**: None identified
- **Startup / cold-start behavior**: Gauge starts at 0, first scrape will show 0
- **Environment / configuration drift**: None identified
- **Performance / scalability**: None identified
- **Backward compatibility**: None identified

## Out of Scope
- Dashboard creation
- Alert routing configuration
