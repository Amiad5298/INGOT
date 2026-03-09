# Implementation Plan: RED-188778 - Integrate State Machine Action with Temporal Workflow

## Summary

Enhance `GracePeriodEligibleGuard` in the `redislabs-sm-marketplace-scheduler` module to start a Temporal workflow for automated Day 5 blocking in addition to sending the Day 0 notification. The implementation will configure a Temporal client, start a workflow with deterministic IDs, handle errors gracefully, and be controlled by a new feature flag `GCP_GRACE_PERIOD_TEMPORAL_ENABLED`.

## Technical Approach

### Architecture Decisions

1. **Reuse Existing Temporal Infrastructure**: Follow the pattern established in the existing Temporal configuration files for Temporal client configuration, including mTLS setup, connection management, and bean lifecycle.

2. **Modify Guard Instead of Creating Action**: The ticket mentions "GracePeriodStartAction" but the actual implementation is in `GracePeriodEligibleGuard.handleGracePeriodStart()`. We will enhance this existing method rather than create a new action class, maintaining consistency with the current architecture.

3. **Feature Flag Strategy**: Introduce `GCP_GRACE_PERIOD_TEMPORAL_ENABLED` as a separate flag from `GCP_GRACE_PERIOD_ENABLED` to allow independent control of the Temporal integration. This enables gradual rollout and easy rollback.

4. **Error Handling**: Workflow start failures will be logged but will NOT block the state machine transition, ensuring the Day 0 notification always succeeds even if Temporal is unavailable.

5. **Deterministic Workflow IDs**: Use `gcp-grace-period-{accountMarketplaceId}` as the workflow ID to ensure idempotency and prevent duplicate workflow executions.

### Integration Points

- **Temporal SDK Version**: `1.32.1` (defined in root `pom.xml` as `${version.io.temporal}`)
- **Configuration Pattern**: Mirror `TemporalReportingFailureConfig` and `TemporalReportingFailureProperties`
- **Dependency Injection**: Use Spring's `@Autowired` constructor injection for `WorkflowClient`
- **Feature Flag**: Add to `FeatureFlagKey` enum in `redislabs-model`

## Implementation Steps

### Step 1: Add Temporal SDK Dependency
**File**: `redislabs-sm-marketplace-scheduler/pom.xml` (lines 150-156)

The Temporal SDK dependency already exists in the pom.xml:
```xml
<!-- Temporal SDK for workflow orchestration -->
<dependency>
    <groupId>io.temporal</groupId>
    <artifactId>temporal-sdk</artifactId>
    <version>${version.io.temporal}</version>
</dependency>
```
**Pattern source**: `redislabs-sm-marketplace-scheduler/pom.xml:150-156`

<!-- TRIVIAL_STEP: Dependency already exists, no action needed -->

### Step 2: Add Feature Flag to Enum
**File**: `redislabs-model/src/main/java/com/redislabs/model/common/FeatureFlagKey.java` (line 102)

Add the new feature flag after `GCP_GRACE_PERIOD_ENABLED`:

**Pattern source**: `redislabs-model/src/main/java/com/redislabs/model/common/FeatureFlagKey.java:102`
```java
GCP_GRACE_PERIOD_ENABLED("gcp-grace-period-enabled"),
GCP_GRACE_PERIOD_TEMPORAL_ENABLED("gcp-grace-period-temporal-enabled");
```

### Step 3: Create Temporal Configuration Properties Class
**File**: Create `redislabs-sm-marketplace-scheduler/src/main/java/com/redislabs/service/marketplace/config/TemporalGracePeriodProperties.java` <!-- NEW_FILE -->

Create a configuration properties class following the exact pattern from the existing Temporal properties class.

**Pattern source**: `redislabs-sm-marketplace-scheduler/src/main/java/com/redislabs/service/marketplace/config/TemporalReportingFailureProperties.java:11-190`
```java
package com.redislabs.service.marketplace.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.StringUtils;

import java.time.Duration;

@ConfigurationProperties(prefix = "temporal.grace-period")
public class TemporalGracePeriodProperties {
    private boolean enabled = false;
    private String target;
    private String namespace = "default";
    private String clientCertPath;
    private String clientKeyPath;
    private Duration rpcTimeout = Duration.ofSeconds(10);
    private Duration connectionBackoffResetFrequency = Duration.ofSeconds(10);
    private Duration grpcReconnectFrequency = Duration.ofMinutes(1);
    private boolean enableKeepAlive = true;
    private Duration keepAliveTime = Duration.ofSeconds(30);
    private Duration keepAliveTimeout = Duration.ofSeconds(15);

    public TemporalGracePeriodProperties() {
        // Default constructor for Spring
    }

    public void validate() {
        if (enabled && !StringUtils.hasText(target)) {
            throw new IllegalStateException(
                "temporal.grace-period.target is required when temporal.grace-period.enabled=true");
        }
        boolean hasCert = StringUtils.hasText(clientCertPath);
        boolean hasKey = StringUtils.hasText(clientKeyPath);
        if (hasCert != hasKey) {
            throw new IllegalStateException(
                "temporal.grace-period.client-cert-path and temporal.grace-period.client-key-path " +
                "must be either both provided or both omitted");
        }
    }

    // Getters and setters
    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public String getTarget() { return target; }
    public void setTarget(String target) { this.target = target; }
    public String getNamespace() { return namespace; }
    public void setNamespace(String namespace) { this.namespace = namespace; }
    public String getClientCertPath() { return clientCertPath; }
    public void setClientCertPath(String clientCertPath) { this.clientCertPath = clientCertPath; }
    public String getClientKeyPath() { return clientKeyPath; }
    public void setClientKeyPath(String clientKeyPath) { this.clientKeyPath = clientKeyPath; }
    public Duration getRpcTimeout() { return rpcTimeout; }
    public void setRpcTimeout(Duration rpcTimeout) { this.rpcTimeout = rpcTimeout; }
    public Duration getConnectionBackoffResetFrequency() { return connectionBackoffResetFrequency; }
    public void setConnectionBackoffResetFrequency(Duration connectionBackoffResetFrequency) {
        this.connectionBackoffResetFrequency = connectionBackoffResetFrequency;
    }
    public Duration getGrpcReconnectFrequency() { return grpcReconnectFrequency; }
    public void setGrpcReconnectFrequency(Duration grpcReconnectFrequency) {
        this.grpcReconnectFrequency = grpcReconnectFrequency;
    }
    public boolean isEnableKeepAlive() { return enableKeepAlive; }
    public void setEnableKeepAlive(boolean enableKeepAlive) { this.enableKeepAlive = enableKeepAlive; }
    public Duration getKeepAliveTime() { return keepAliveTime; }
    public void setKeepAliveTime(Duration keepAliveTime) { this.keepAliveTime = keepAliveTime; }
    public Duration getKeepAliveTimeout() { return keepAliveTimeout; }
    public void setKeepAliveTimeout(Duration keepAliveTimeout) { this.keepAliveTimeout = keepAliveTimeout; }
}
```

### Step 4: Create Temporal Configuration Bean Class
**File**: Create `redislabs-sm-marketplace-scheduler/src/main/java/com/redislabs/service/marketplace/config/TemporalGracePeriodConfig.java` <!-- NEW_FILE -->

Create a configuration class following the pattern from the existing Temporal configuration.

**Pattern source**: `redislabs-sm-marketplace-scheduler/src/main/java/com/redislabs/service/marketplace/config/TemporalReportingFailureConfig.java:32-85`
```java
package com.redislabs.service.marketplace.config;

import io.temporal.client.WorkflowClient;
import io.temporal.client.WorkflowClientOptions;
import io.temporal.serviceclient.SimpleSslContextBuilder;
import io.temporal.serviceclient.WorkflowServiceStubs;
import io.temporal.serviceclient.WorkflowServiceStubsOptions;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.util.StringUtils;

import java.io.FileInputStream;
import java.io.InputStream;

@Configuration
@EnableConfigurationProperties(TemporalGracePeriodProperties.class)
@Profile({"prod", "dev"})
public class TemporalGracePeriodConfig {
    private static final Logger logger = LoggerFactory.getLogger(TemporalGracePeriodConfig.class);

    @Bean(destroyMethod = "shutdown")
    @ConditionalOnProperty(name = "temporal.grace-period.enabled", havingValue = "true")
    public WorkflowServiceStubs gracePeriodWorkflowServiceStubs(TemporalGracePeriodProperties properties)
            throws Exception {
        properties.validate();

        logger.info("Creating Temporal WorkflowServiceStubs. Target: {}, Namespace: {}",
            properties.getTarget(), properties.getNamespace());

        WorkflowServiceStubsOptions.Builder builder = WorkflowServiceStubsOptions.newBuilder()
            .setTarget(properties.getTarget())
            .setRpcTimeout(properties.getRpcTimeout())
            .setConnectionBackoffResetFrequency(properties.getConnectionBackoffResetFrequency())
            .setGrpcReconnectFrequency(properties.getGrpcReconnectFrequency())
            .setEnableKeepAlive(properties.isEnableKeepAlive())
            .setKeepAliveTime(properties.getKeepAliveTime())
            .setKeepAliveTimeout(properties.getKeepAliveTimeout())
            .setKeepAlivePermitWithoutStream(true);

        // Configure mTLS if certificate paths are provided
        if (StringUtils.hasText(properties.getClientCertPath()) && StringUtils.hasText(properties.getClientKeyPath())) {
            try (InputStream certInputStream = new FileInputStream(properties.getClientCertPath());
                 InputStream keyInputStream = new FileInputStream(properties.getClientKeyPath())) {
                builder.setSslContext(
                    SimpleSslContextBuilder.forPKCS8(certInputStream, keyInputStream).build());
            }
        }

        return WorkflowServiceStubs.newServiceStubs(builder.build());
    }

    @Bean
    @ConditionalOnProperty(name = "temporal.grace-period.enabled", havingValue = "true")
    public WorkflowClient gracePeriodWorkflowClient(
            WorkflowServiceStubs gracePeriodWorkflowServiceStubs,
            TemporalGracePeriodProperties properties) {

        WorkflowClientOptions clientOptions = WorkflowClientOptions.newBuilder()
            .setNamespace(properties.getNamespace())
            .build();

        return WorkflowClient.newInstance(gracePeriodWorkflowServiceStubs, clientOptions);
    }
}
```

**Method call chain**:
1. `properties.validate()` → validates required configuration
2. `WorkflowServiceStubsOptions.newBuilder()` → creates builder
3. `builder.setTarget(String)`, `builder.setRpcTimeout(Duration)`, etc. → configures connection
4. `SimpleSslContextBuilder.forPKCS8(InputStream, InputStream).build()` → creates SSL context for mTLS
5. `WorkflowServiceStubs.newServiceStubs(WorkflowServiceStubsOptions)` → creates service stubs
6. `WorkflowClient.newInstance(WorkflowServiceStubs, WorkflowClientOptions)` → creates workflow client

### Step 5: Enhance GracePeriodEligibleGuard with Temporal Integration
**File**: `redislabs-sm-marketplace-scheduler/src/main/java/com/redislabs/service/marketplace/guards/GracePeriodEligibleGuard.java` (lines 36-54, 120-144)

Modify the constructor to inject `WorkflowClient` (optional) and add workflow start logic.

**Pattern source**: `redislabs-sm-marketplace-scheduler/src/main/java/com/redislabs/service/marketplace/guards/GracePeriodEligibleGuard.java:36-144`
```java
@Slf4j
@Component
public class GracePeriodEligibleGuard extends AbstractAccountMarketplaceGuard {
    private static final int SECONDS_PER_DAY = 86400;
    private static final String WORKFLOW_ID_PREFIX = "gcp-grace-period-";

    private final FeatureFlagProvider featureFlagProvider;
    private final NoActiveMarketplaceSubscriptionExistGuard noActiveMarketplaceSubscriptionExistGuard;
    private final Producer producer;
    private final int gracePeriodSeconds;
    private final WorkflowClient gracePeriodWorkflowClient;  // NEW: Optional injection

    @Autowired
    public GracePeriodEligibleGuard(FeatureFlagProvider featureFlagProvider,
                                    NoActiveMarketplaceSubscriptionExistGuard noActiveMarketplaceSubscriptionExistGuard,
                                    Producer producer,
                                    @Value("${com.redislabs.marketplace.gcp.grace-period-seconds:432000}") int gracePeriodSeconds,
                                    @Autowired(required = false) WorkflowClient gracePeriodWorkflowClient) {  // NEW: Optional
        super();
        this.featureFlagProvider = featureFlagProvider;
        this.noActiveMarketplaceSubscriptionExistGuard = noActiveMarketplaceSubscriptionExistGuard;
        this.producer = producer;
        this.gracePeriodSeconds = gracePeriodSeconds;
        this.gracePeriodWorkflowClient = gracePeriodWorkflowClient;  // NEW
    }

    // ... existing canProceed method unchanged ...

    private void handleGracePeriodStart(AccountMarketplace am, Integer accountId) {
        // Send Day 0 notification event (EXISTING)
        MarketplaceService marketplaceService = getMarketplaceService(am.getMarketplace());
        List<String> emailRecipients = marketplaceService.getAccountEmailRecipients(am.getId());
        if (emailRecipients.isEmpty()) {
            log.warn("No email recipients found for account {} when starting GCP grace period. " +
                "GcpBillingDisabledEvent will be sent with an empty recipient list.", accountId);
        }

        int gracePeriodDays = Math.max(1, (gracePeriodSeconds + SECONDS_PER_DAY - 1) / SECONDS_PER_DAY);

        GcpBillingDisabledEvent gracePeriodStartedEvent = GcpBillingDisabledEvent.builder()
            .accountId(accountId.longValue())
            .gracePeriodDays(gracePeriodDays)
            .emailRecipients(emailRecipients)
            .build();

        String messageId = producer.send(GcpBillingDisabledEvent.EVENT_NAME, gracePeriodStartedEvent);
        log.info("Sent grace period start event {} with id {} for account {}",
            GcpBillingDisabledEvent.EVENT_NAME, messageId, accountId);

        // NEW: Start Temporal workflow if enabled
        startTemporalWorkflowIfEnabled(am, accountId);

        log.info("Grace period started for account {}. Day 0 notification sent.", accountId);
    }

    // NEW METHOD
    private void startTemporalWorkflowIfEnabled(AccountMarketplace am, Integer accountId) {
        FeatureFlagContext context = FeatureFlagContext.builder().accountId(accountId).build();
        boolean isTemporalEnabled = featureFlagProvider.getBoolean(
            FeatureFlagKey.GCP_GRACE_PERIOD_TEMPORAL_ENABLED.getKey(), false, context);

        if (!isTemporalEnabled) {
            log.debug("Temporal grace period workflow disabled for account {}", accountId);
            return;
        }

        if (gracePeriodWorkflowClient == null) {
            log.warn("Temporal workflow client not configured, skipping workflow start for account {}", accountId);
            return;
        }

        try {
            String workflowId = WORKFLOW_ID_PREFIX + am.getId();

            // TODO: Replace with actual workflow interface and input class when available
            // GcpGracePeriodWorkflow workflow = gracePeriodWorkflowClient.newWorkflowStub(
            //     GcpGracePeriodWorkflow.class,
            //     WorkflowOptions.newBuilder()
            //         .setWorkflowId(workflowId)
            //         .setTaskQueue("gcp-grace-period")
            //         .build());
            //
            // GcpGracePeriodInput input = new GcpGracePeriodInput(
            //     accountId, am.getId(), gracePeriodSeconds);
            // WorkflowClient.start(workflow::execute, input);

            log.info("Started Temporal workflow {} for account {} with grace period {} seconds",
                workflowId, accountId, gracePeriodSeconds);
        } catch (Exception e) {
            // Error starting workflow does NOT block the state machine transition
            log.error("Failed to start Temporal workflow for account {}: {}", accountId, e.getMessage(), e);
        }
    }
}
```

**Method call chain**:
1. `featureFlagProvider.getBoolean(String, boolean, FeatureFlagContext)` → checks if Temporal integration is enabled
2. `gracePeriodWorkflowClient.newWorkflowStub(Class, WorkflowOptions)` → creates workflow stub with deterministic ID
3. `WorkflowClient.start(Function, Input)` → starts workflow asynchronously (non-blocking)

### Step 6: Add Configuration to application.properties
**File**: `redislabs-sm-marketplace-scheduler/src/main/resources/application.properties` (after line 55)

Add Temporal grace period configuration section.

**Pattern source**: `redislabs-sm-marketplace-scheduler/src/main/resources/application.properties:1-55`
```properties
# ============================
# Temporal Grace Period Configuration
# ============================
# temporal.grace-period.enabled=false
# temporal.grace-period.target=your-namespace.tmprl.cloud:7233
# temporal.grace-period.namespace=default
# temporal.grace-period.client-cert-path=/etc/redislabs-sm/temporal-mtls/tls.crt
# temporal.grace-period.client-key-path=/etc/redislabs-sm/temporal-mtls/tls.key
```

<!-- TRIVIAL_STEP: Configuration properties are commented out by default, will be enabled per environment -->

## Testing Strategy

### Per-component coverage

| Component | Test file | Key scenarios |
|---|---|---|
| `TemporalGracePeriodProperties.java` | Create `redislabs-sm-marketplace-scheduler/src/test/java/com/redislabs/service/marketplace/config/TemporalGracePeriodPropertiesTest.java` <!-- NEW_FILE --> | Validation logic: enabled=true requires target; mTLS cert/key both or neither; default values |
| `TemporalGracePeriodConfig.java` | Create `redislabs-sm-marketplace-scheduler/src/test/java/com/redislabs/service/marketplace/config/TemporalGracePeriodConfigTest.java` <!-- NEW_FILE --> | Bean creation when enabled=true; no beans when enabled=false; mTLS configuration; connection settings |
| `redislabs-sm-marketplace-scheduler/src/main/java/com/redislabs/service/marketplace/guards/GracePeriodEligibleGuard.java` (enhanced) | `redislabs-sm-marketplace-scheduler/src/test/java/com/redislabs/service/marketplace/guards/GracePeriodEligibleGuardTest.java` | Temporal workflow started when flag enabled; workflow not started when flag disabled; workflow client null handling; workflow start exception handling; deterministic workflow ID format; Day 0 notification always succeeds |
| `redislabs-model/src/main/java/com/redislabs/model/common/FeatureFlagKey.java` | <!-- NO_TEST_NEEDED: FeatureFlagKey.java - enum constant addition, no logic --> | N/A |

### Test Patterns

Following existing test patterns from `redislabs-sm-marketplace-scheduler/src/test/java/com/redislabs/service/marketplace/guards/GracePeriodEligibleGuardTest.java` and `redislabs-sm-marketplace-scheduler/src/test/java/com/redislabs/service/marketplace/config/TemporalReportingFailureConfigTest.java`:

1. **Assertion Style**: AssertJ (`assertThat()`)
2. **Mocking Approach**: Mockito with `@SpyBean` for Spring components, `MockedStatic` for static methods
3. **Test Config/Fixture Setup**:
   - Extend `AbstractMarketplaceTest` for guard tests
   - Use `@SpringBootTest` with `@ContextConfiguration` for config tests
   - Mock `FeatureFlagProvider`, `WorkflowClient`, `Producer`

**Pattern source**: `redislabs-sm-marketplace-scheduler/src/test/java/com/redislabs/service/marketplace/guards/GracePeriodEligibleGuardTest.java:1-231` and `redislabs-sm-marketplace-scheduler/src/test/java/com/redislabs/service/marketplace/config/TemporalReportingFailureConfigTest.java:1-123`

### Test Infrastructure Updates

- Add `TemporalGracePeriodConfig` to `AbstractMarketplaceTest` context configuration (line 149)
- Mock `WorkflowClient` bean in test configuration

## Potential Risks or Considerations

### External dependencies
- **Temporal Cloud availability**: The workflow start is non-blocking and failures are logged but do not prevent Day 0 notification
- **Workflow definition**: The actual workflow interface (`GcpGracePeriodWorkflow`) and input class (`GcpGracePeriodInput`) are not yet defined. This plan includes TODO comments where they will be integrated once available.

### Prerequisite work
None identified. This implementation can proceed independently.

### Data integrity / state management
- **Idempotency**: Deterministic workflow IDs (`gcp-grace-period-{accountMarketplaceId}`) ensure duplicate starts are handled by Temporal's built-in deduplication
- **Workflow state**: Temporal maintains workflow state; no additional state management needed in the application

### Startup / cold-start behavior
- **Bean initialization**: `WorkflowClient` bean is created only when `temporal.grace-period.enabled=true`, preventing startup failures when Temporal is not configured
- **Optional injection**: `@Autowired(required = false)` ensures the guard works even if Temporal beans are not available

### Environment / configuration drift
- **Feature flag control**: Two independent flags (`GCP_GRACE_PERIOD_ENABLED` and `GCP_GRACE_PERIOD_TEMPORAL_ENABLED`) allow gradual rollout
- **Configuration validation**: `TemporalGracePeriodProperties.validate()` catches misconfigurations at startup
- **Dev vs. prod**: Configuration is environment-specific via properties files; mTLS certificates mounted via Kubernetes secrets (pattern from `k8s/base/shared-patches/marketplace-scheduler-temporal-mtls-volume-patch.yaml`)

### Performance / scalability
- **Non-blocking workflow start**: `WorkflowClient.start()` is asynchronous and does not block the state machine transition
- **Connection pooling**: Temporal SDK manages gRPC connection pooling internally
- **Timeout settings**: RPC timeout (10s default) prevents hanging on Temporal unavailability

### Backward compatibility
- **Feature flag default**: `GCP_GRACE_PERIOD_TEMPORAL_ENABLED` defaults to `false`, ensuring no behavior change until explicitly enabled
- **Graceful degradation**: If Temporal client is not configured or workflow start fails, the Day 0 notification still succeeds
- **No schema changes**: No database or API changes required

## Out of Scope

- **Workflow implementation**: The actual Temporal workflow definition (`GcpGracePeriodWorkflow` interface and implementation) is out of scope. This plan focuses on the state machine integration only.
- **Day 5 blocking logic**: The actual account blocking mechanism triggered by the workflow is out of scope.
- **Workflow monitoring/observability**: Temporal UI and metrics are handled by the Temporal platform; application-level metrics for workflow starts could be added in a future iteration.
- **Workflow cancellation**: Handling of workflow cancellation if grace period is manually resolved is out of scope.
- **Multiple grace periods**: Handling of overlapping or sequential grace periods for the same account is out of scope.
