# Implementation Plan: AMI-39 - Create Platform Configuration Guide

**Ticket:** [AMI-39](https://linear.app/amiadspec/issue/AMI-39/create-platform-configuration-guide)
**Status:** Draft
**Date:** 2026-01-28

---

## Summary

This ticket creates comprehensive documentation for configuring credentials and settings for each of the 6 supported ticket platforms. While a configuration template exists (`spec/config/templates/fetch_config.template`), users need a clear, user-friendly guide explaining:

1. **Two authentication modes** - Auggie MCP integration (primary) vs fallback credentials (direct API)
2. **Platform-specific setup** - Where to obtain API keys/tokens for each platform
3. **Configuration file setup** - How to configure credentials securely using environment variables
4. **Troubleshooting** - Common credential issues and their solutions

**Why This Matters:**
- Azure DevOps, Monday, and Trello **require** fallback credentials (no Auggie MCP integration)
- Jira, Linear, and GitHub can optionally use fallback credentials as a backup
- Credential configuration errors are a common source of user frustration
- The existing placeholder in `docs/platform-configuration.md` has TODOs that need filling

**Target File:** `docs/platform-configuration.md` (replace placeholder content)

---

## Technical Approach

### Documentation Strategy

The guide should follow a logical structure that helps users understand:

1. **When credentials are needed** - Understanding the two authentication modes
2. **What credentials are required** - Platform-specific requirements (canonical keys from AMI-22/AMI-31)
3. **Where to get credentials** - Step-by-step for each platform's API portal
4. **How to configure them** - Config file examples with environment variable best practices
5. **How to verify** - Testing the configuration works

### Architecture Reference

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         AUTHENTICATION MODES                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│  PRIMARY: Auggie MCP Integration                                                │
│  • Platforms: Jira, Linear, GitHub                                             │
│  • Authentication handled by Auggie agent configuration                         │
│  • User sets up credentials in Auggie, not SPEC                                │
│  • No configuration needed in SPEC (works out of the box)                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│  FALLBACK: Direct API Access                                                    │
│  • Platforms: ALL 6 (Azure DevOps, Monday, Trello REQUIRE this)                │
│  • Authentication via FALLBACK_* config keys                                    │
│  • Uses AuthenticationManager (AMI-22) for credential retrieval                 │
│  • Uses DirectAPIFetcher (AMI-31) for HTTP requests                            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Credential Requirements Summary

| Platform | Auggie MCP | Credential Keys | Required Fields |
|----------|------------|-----------------|-----------------|
| **Jira** | ✅ Primary | `FALLBACK_JIRA_*` | `url`, `email`, `token` |
| **Linear** | ✅ Primary | `FALLBACK_LINEAR_*` | `api_key` |
| **GitHub** | ✅ Primary | `FALLBACK_GITHUB_*` | `token` |
| **Azure DevOps** | ❌ | `FALLBACK_AZURE_DEVOPS_*` | `organization`, `pat` |
| **Monday** | ❌ | `FALLBACK_MONDAY_*` | `api_key` |
| **Trello** | ❌ | `FALLBACK_TRELLO_*` | `api_key`, `token` |

---

## File Requiring Changes

### `docs/platform-configuration.md`

**Change Type:** Complete rewrite (replace placeholder)

**Current Content (placeholder):**
```markdown
# Platform Configuration Guide

> **TODO:** This is a placeholder document. Fill in configuration steps for each platform.
...
```

**New Structure:**
1. Overview - Two authentication modes explained
2. Quick Reference Table - All platforms at a glance
3. Credential Key Aliases - Supported alternative key names
4. Setting Default Platform - `DEFAULT_PLATFORM` configuration
5. Platforms with Auggie Integration (Jira, Linear, GitHub)
6. Platforms Requiring Fallback Credentials (Azure DevOps, Monday, Trello)
7. Configuration File Examples
8. Environment Variable Security
9. Verifying Configuration
10. Troubleshooting

---

## Implementation Steps

### Step 1: Document Overview and Authentication Modes

Replace the placeholder header and overview with a comprehensive explanation of the two authentication paths.

**Key concepts to explain:**
- Auggie MCP = primary path, credentials configured in Auggie
- Fallback credentials = direct API access, configured in SPEC
- When each mode is used (AUTO strategy tries Auggie first)

### Step 2: Create Quick Reference Table

Add a consolidated reference table showing all platforms with their credential requirements:

```markdown
| Platform | Auggie Support | Fallback Required | Config Keys |
|----------|---------------|-------------------|-------------|
| Jira | ✅ | Optional | `FALLBACK_JIRA_URL`, `FALLBACK_JIRA_EMAIL`, `FALLBACK_JIRA_TOKEN` |
| Linear | ✅ | Optional | `FALLBACK_LINEAR_API_KEY` |
| GitHub | ✅ | Optional | `FALLBACK_GITHUB_TOKEN` |
| Azure DevOps | ❌ | **Required** | `FALLBACK_AZURE_DEVOPS_ORGANIZATION`, `FALLBACK_AZURE_DEVOPS_PAT` |
| Monday | ❌ | **Required** | `FALLBACK_MONDAY_API_KEY` |
| Trello | ❌ | **Required** | `FALLBACK_TRELLO_API_KEY`, `FALLBACK_TRELLO_TOKEN` |
```

### Step 2b: Document Credential Key Aliases

Add a subsection documenting supported credential key aliases for backward compatibility:

```markdown
### Credential Key Aliases

For convenience, SPEC accepts these alternative key names that are automatically
normalized to canonical keys:

| Platform | Alias | Canonical Key |
|----------|-------|---------------|
| Azure DevOps | `org` | `organization` |
| Azure DevOps | `token` | `pat` |
| Jira | `base_url` | `url` |
| Trello | `api_token` | `token` |

Example: `FALLBACK_AZURE_DEVOPS_ORG=myorg` is equivalent to `FALLBACK_AZURE_DEVOPS_ORGANIZATION=myorg`
```

### Step 3: Document Auggie-Integrated Platforms

For Jira, Linear, and GitHub:
- Explain these work out-of-the-box with Auggie
- Document OPTIONAL fallback credential setup for backup/CI environments
- Link to official API documentation

### Step 4: Document Fallback-Required Platforms

For Azure DevOps, Monday, and Trello:
- Explain these REQUIRE fallback credentials
- Step-by-step credential acquisition instructions
- Config file examples

### Step 5: Add Platform-Specific Setup Sections

Create detailed sections for each platform with:

#### Jira
- Where to get API token: Atlassian account settings → API tokens
- Required fields: `url` (instance URL), `email` (account email), `token` (API token)
- Note about Cloud vs Server/Data Center

#### Linear
- Where to get API key: Linear Settings → API → Personal API keys
- Required fields: `api_key`
- Note about workspace access

#### GitHub
- Where to get token: GitHub Settings → Developer settings → Personal access tokens
- Required fields: `token`
- Note about fine-grained vs classic tokens
- **Required scopes for classic tokens:** `repo` (full repository access) or `public_repo` (public only)
- **Required permissions for fine-grained tokens:** Issues (Read), Pull requests (Read)

#### Azure DevOps
- Where to get PAT: Azure DevOps → User settings → Personal access tokens
- Required fields: `organization` (org name), `pat` (Personal Access Token)
- **Required PAT scopes:** Work Items (Read)
- Note about PAT expiration (max 1 year) and rotation reminders

#### Monday
- Where to get API key: monday.com → Profile → Admin → API
- Required fields: `api_key`
- Note about API v2

#### Trello
- Where to get credentials: Trello Power-Up Admin Portal
- Required fields: `api_key`, `token` (OAuth token)
- Two-step process: API key first, then token authorization

### Step 5b: Document Default Platform Configuration (AC5)

Add a dedicated section explaining how to set the default platform:

```markdown
## Setting Default Platform

Configure a default platform to avoid specifying `--platform` on every command.
This is useful when you primarily work with one ticket system.

### Configuration

```bash
# ~/.spec-config
DEFAULT_PLATFORM=jira
```

### Supported Values

| Value | Platform |
|-------|----------|
| `jira` | Jira |
| `linear` | Linear |
| `github` | GitHub Issues |
| `azure_devops` | Azure DevOps |
| `monday` | Monday.com |
| `trello` | Trello |

### Usage

With `DEFAULT_PLATFORM=jira` configured:

```bash
# These are equivalent:
spec PROJ-123
spec --platform jira PROJ-123
```

> **Note:** The `--platform` flag always overrides the default when specified.
```

### Step 6: Add Configuration File Examples

Provide complete example configurations:

```bash
# ~/.spec-config or .spec file

# ============================================================
# DEFAULT PLATFORM (optional - avoids --platform flag)
# ============================================================
DEFAULT_PLATFORM=jira

# ============================================================
# AGENT CONFIGURATION (for Auggie users)
# ============================================================
AI_BACKEND=auggie
AGENT_INTEGRATION_JIRA=true
AGENT_INTEGRATION_LINEAR=true
AGENT_INTEGRATION_GITHUB=true
AGENT_INTEGRATION_AZURE_DEVOPS=false
AGENT_INTEGRATION_TRELLO=false
AGENT_INTEGRATION_MONDAY=false

# ============================================================
# FALLBACK CREDENTIALS (required for Azure DevOps, Monday, Trello)
# ============================================================
# Azure DevOps (REQUIRED - no Auggie integration)
FALLBACK_AZURE_DEVOPS_ORGANIZATION=myorg
FALLBACK_AZURE_DEVOPS_PAT=${AZURE_DEVOPS_PAT}

# Trello (REQUIRED - no Auggie integration)
FALLBACK_TRELLO_API_KEY=${TRELLO_API_KEY}
FALLBACK_TRELLO_TOKEN=${TRELLO_TOKEN}

# Monday (REQUIRED - no Auggie integration)
FALLBACK_MONDAY_API_KEY=${MONDAY_API_KEY}

# Jira (OPTIONAL - for fallback when Auggie unavailable)
# FALLBACK_JIRA_URL=https://company.atlassian.net
# FALLBACK_JIRA_EMAIL=user@example.com
# FALLBACK_JIRA_TOKEN=${JIRA_API_TOKEN}
```

### Step 7: Document Environment Variable Security

Add a dedicated section on security best practices:
- Never hardcode secrets in config files
- Use `${VAR_NAME}` syntax for environment variable expansion
- Setting environment variables in shell profiles
- CI/CD secret management guidance

### Step 8: Add Verification Instructions

Document how to verify configuration is working:

```bash
# Check which platforms are configured
spec --config

# Test fetching a ticket from each configured platform
spec <ticket-url-or-id>
```

### Step 9: Add Troubleshooting Section

Document common issues and solutions:
- "No credentials configured" error
- "Missing required field" errors
- Environment variable not expanding (unexpanded `${VAR}`)
- Authentication failures (401/403 errors)
- Network/timeout issues

---

## Documentation Content Specification

### Section: Overview

**Title:** Overview

**Content:**
- Explain SPEC supports 6 ticket platforms
- Describe two authentication modes:
  1. **Auggie MCP Integration (Primary)** - Jira, Linear, GitHub work automatically
  2. **Fallback Credentials (Direct API)** - Required for Azure DevOps, Monday, Trello
- Explain the AUTO fetch strategy (tries Auggie first, falls back to direct)
- Link to related documentation (README, AMI-38)

### Section: Platforms with Auggie Integration

**Title:** Platforms with Auggie Integration

**Platforms:** Jira, Linear, GitHub

**Content per platform:**
1. Header with platform name
2. Statement that this works out-of-the-box with Auggie
3. OPTIONAL fallback credential setup (for CI/backup)
4. Required credential keys with descriptions
5. Link to official API documentation
6. Configuration example

**Example for Jira:**
```markdown
### Jira

Jira is fully integrated with Auggie's MCP tools. When using Auggie, no additional
configuration is needed—Auggie uses its own Jira integration.

#### Optional Fallback Credentials

For environments without Auggie (CI/CD, backup), configure fallback credentials:

| Config Key | Description |
|------------|-------------|
| `FALLBACK_JIRA_URL` | Your Jira instance URL (e.g., `https://company.atlassian.net`) |
| `FALLBACK_JIRA_EMAIL` | Your Atlassian account email |
| `FALLBACK_JIRA_TOKEN` | API token (not password) |

#### Getting an API Token

1. Go to [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Click "Create API token"
3. Give it a descriptive name (e.g., "SPEC CLI")
4. Copy the token immediately (it won't be shown again)
5. Store it in an environment variable: `export JIRA_API_TOKEN="your-token"`

#### Configuration

```bash
# ~/.spec-config
FALLBACK_JIRA_URL=https://company.atlassian.net
FALLBACK_JIRA_EMAIL=user@example.com
FALLBACK_JIRA_TOKEN=${JIRA_API_TOKEN}
```
```

### Section: Platforms Requiring Fallback Credentials

**Title:** Platforms Requiring Fallback Credentials

**Platforms:** Azure DevOps, Monday, Trello

**Content per platform:**
1. Header with platform name
2. Clear statement that credentials are REQUIRED
3. Required credential keys with descriptions
4. Step-by-step credential acquisition
5. Link to official documentation
6. Configuration example
7. Platform-specific gotchas/notes

### Section: Environment Variable Security

**Title:** Security Best Practices

**Content:**
- Never commit secrets to version control
- Use environment variables for all sensitive values
- `${VAR_NAME}` syntax for referencing env vars in config
- Examples for bash/zsh profile setup
- CI/CD secret configuration guidance

### Section: Verifying Configuration

**Title:** Verifying Your Configuration

**Content:**
- Using `spec --config` to check configuration status
- Testing with a real ticket
- Expected output examples
- What success looks like

### Section: Troubleshooting

**Title:** Troubleshooting

**Content:**
- Table of common errors with solutions
- Debugging tips (verbose logging)
- Platform-specific issues
- Where to get help

### Section: Default Platform (NEW - AC5)

**Title:** Setting Default Platform

**Content:**
- What `DEFAULT_PLATFORM` does
- Supported platform values
- Configuration example
- Interaction with `--platform` flag

### Section: Credential Key Aliases (NEW - AC10)

**Title:** Credential Key Aliases

**Content:**
- Table of supported aliases per platform
- Explanation that aliases are normalized to canonical keys
- Example usage

---

## Acceptance Criteria

From the Linear ticket:

- [ ] **AC1:** Documentation explains the two authentication modes (agent integration vs. fallback credentials)
- [ ] **AC2:** Each of the 6 platforms has a dedicated setup section
- [ ] **AC3:** Required credentials for each platform are clearly listed
- [ ] **AC4:** Step-by-step instructions for platforms requiring fallback credentials
- [ ] **AC5:** Instructions for setting `default_platform` configuration *(addressed in Step 5b)*
- [ ] **AC6:** Common error messages and their solutions are documented
- [ ] **AC7:** Security best practices for credential storage are mentioned

### Additional Criteria

- [ ] **AC8:** Links to official platform API documentation are included
- [ ] **AC9:** Configuration file examples are complete and tested
- [ ] **AC10:** Credential key aliases are documented *(addressed in Step 2b)*
- [ ] **AC11:** Environment variable expansion syntax is explained (`${VAR_NAME}`)
- [ ] **AC12:** Verification instructions using `spec --config` are included
- [ ] **AC13:** Required API scopes/permissions are documented per platform *(GitHub, Azure DevOps)*

---

## Testing/Validation Strategy

### Content Validation

1. **Technical accuracy** - Verify all credential keys match implementation:
   - Cross-reference with `PLATFORM_REQUIRED_CREDENTIALS` in `spec/config/fetch_config.py`
   - Verify against `AuthenticationManager` docstrings in `spec/integrations/auth.py`

2. **Link validation** - All external links are valid and point to correct locations

3. **Example validation** - Config examples parse correctly and match the template format

### User Experience Validation

1. **Completeness check** - Follow the guide for at least one platform to verify steps work
2. **Error message validation** - Intentionally misconfigure to verify error messages match troubleshooting section
3. **Cross-reference** - Ensure README.md links to this guide correctly

### Checklist

```bash
# Verify config keys match implementation
grep -E "PLATFORM_REQUIRED_CREDENTIALS" spec/config/fetch_config.py

# Verify credential aliases
grep -E "CREDENTIAL_ALIASES" spec/config/fetch_config.py

# Test the spec --config command
spec --config

# Verify external links (manual)
# - Atlassian API tokens
# - Linear API settings
# - GitHub PAT settings
# - Azure DevOps PAT page
# - Monday.com API
# - Trello developer portal
```

---

## Dependencies

### Upstream Dependencies

| Ticket | Component | Status | Description |
|--------|-----------|--------|-------------|
| AMI-22 | AuthenticationManager | ✅ | Defines canonical credential keys per platform |
| AMI-31 | DirectAPIFetcher | ✅ | Uses credentials for direct API access |
| AMI-33 | Fetch Config | ✅ | Configuration schema and validation |
| AMI-25 | CLI Migration | ✅ | Platform-agnostic CLI with `--platform` flag |

### Related Tickets (Parallel Work)

| Ticket | Title | Relationship |
|--------|-------|--------------|
| [AMI-38](https://linear.app/amiadspec/issue/AMI-38) | Update README for Multi-Platform | Links to this guide |
| [AMI-42](https://linear.app/amiadspec/issue/AMI-42) | Update spec --config Output | Shows configuration status |
| [AMI-43](https://linear.app/amiadspec/issue/AMI-43) | Audit User-Facing Strings | Error messages referenced here |

---

## Estimated Effort

| Phase | Description | Estimate |
|-------|-------------|----------|
| Step 1-2 | Overview and quick reference | 0.25 day |
| Step 3 | Auggie-integrated platforms (Jira, Linear, GitHub) | 0.25 day |
| Step 4-5 | Fallback-required platforms (Azure DevOps, Monday, Trello) | 0.25 day |
| Step 6-7 | Configuration examples and security | 0.15 day |
| Step 8-9 | Verification and troubleshooting | 0.1 day |
| Validation | Link checking, testing examples | 0.1 day |
| **Total** | | **~1 day** |

---

## Before/After Examples

### Before (Placeholder)

```markdown
# Platform Configuration Guide

> **TODO:** This is a placeholder document. Fill in configuration steps for each platform.

## Platforms Requiring Fallback Credentials

### Azure DevOps

TODO: Document credential setup steps for Azure DevOps.
```

### After (Documented)

```markdown
# Platform Configuration Guide

> Complete documentation for configuring credentials for SPEC's 6 supported ticket platforms.

## Overview

SPEC supports two authentication modes for fetching tickets:

1. **Auggie MCP Integration (Primary)** - Jira, Linear, and GitHub work automatically...
2. **Fallback Credentials (Direct API)** - Required for Azure DevOps, Monday, and Trello...

## Platforms Requiring Fallback Credentials

### Azure DevOps

Azure DevOps does not have Auggie MCP integration. Fallback credentials are **required**.

| Config Key | Description |
|------------|-------------|
| `FALLBACK_AZURE_DEVOPS_ORGANIZATION` | Your Azure DevOps organization name |
| `FALLBACK_AZURE_DEVOPS_PAT` | Personal Access Token |

#### Getting a Personal Access Token (PAT)

1. Navigate to Azure DevOps → User settings (top right) → Personal access tokens
2. Click "New Token"
3. Set a name and expiration date
4. Under "Scopes", select:
   - Work Items: Read
5. Click "Create" and copy the token immediately

#### Configuration

```bash
# Set environment variable (add to ~/.bashrc or ~/.zshrc)
export AZURE_DEVOPS_PAT="your-personal-access-token"

# ~/.spec-config
FALLBACK_AZURE_DEVOPS_ORGANIZATION=myorg
FALLBACK_AZURE_DEVOPS_PAT=${AZURE_DEVOPS_PAT}
```

> **Note:** PATs have expiration dates. Set a calendar reminder to rotate before expiry.
```

---

## External Links Reference

Include these official documentation links in the guide:

| Platform | Link | Purpose |
|----------|------|---------|
| Jira | https://id.atlassian.com/manage-profile/security/api-tokens | API token creation |
| Jira | https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/ | REST API docs |
| Linear | https://linear.app/settings/api | Personal API keys |
| Linear | https://developers.linear.app/docs/graphql/working-with-the-graphql-api | GraphQL API docs |
| GitHub | https://github.com/settings/tokens | Personal access tokens |
| GitHub | https://docs.github.com/en/rest/issues | REST API docs |
| Azure DevOps | https://dev.azure.com/ → User settings → Personal access tokens | PAT creation |
| Azure DevOps | https://learn.microsoft.com/en-us/rest/api/azure/devops/ | REST API docs |
| Monday | https://monday.com/developers/apps/manage | API access |
| Monday | https://developer.monday.com/api-reference/docs | GraphQL API docs |
| Trello | https://trello.com/power-ups/admin | API key |
| Trello | https://developer.atlassian.com/cloud/trello/ | REST API docs |

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-01-28 | AI Assistant | Initial draft created |
