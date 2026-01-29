# Platform Configuration Guide

> Complete documentation for configuring credentials for SPEC's 6 supported ticket platforms.

## Quick Start Checklist

1. **Choose your platform(s)** – Identify which ticket platforms you'll use (Jira, Linear, GitHub, Azure DevOps, Monday, Trello)
2. **Set default platform** *(optional)* – Add `DEFAULT_PLATFORM=<platform>` to `~/.spec-config` to avoid using `--platform` flag
3. **Configure fallback credentials** *(if required)* – Azure DevOps, Monday, and Trello **require** credentials; Jira/Linear/GitHub need them only as a backup
4. **Verify configuration** – Run `spec --config` to confirm your setup

---

## Overview

SPEC supports fetching tickets from 6 platforms:

- **Jira** – Atlassian's issue tracking system
- **Linear** – Modern project management for software teams
- **GitHub Issues** – GitHub's built-in issue tracker
- **Azure DevOps** – Microsoft's DevOps platform (Work Items)
- **Monday.com** – Work management platform
- **Trello** – Kanban-style project boards

### Two Authentication Modes

SPEC uses two authentication modes to fetch tickets. **"Agent integration"** refers to using an AI coding assistant's built-in platform connections (e.g., Auggie MCP tools), while **"fallback credentials"** means providing your own API keys for direct API access.

1. **Agent Integration via Auggie MCP (Primary)**
   - Platforms: Jira, Linear, GitHub
   - Authentication is handled by Auggie's built-in MCP (Model Context Protocol) integrations
   - No configuration needed in SPEC—works out of the box when using Auggie
   - Credentials are managed in your Auggie agent settings
   - **Note:** "Auggie" is the specific AI agent implementation; if you're using a different agent or running SPEC standalone, use fallback credentials instead

2. **Fallback Credentials (Direct API)**
   - Platforms: **All 6** (Azure DevOps, Monday, Trello **require** this)
   - Authentication via `FALLBACK_*` configuration keys
   - Credentials stored in `~/.spec-config` or `.spec` file
   - Used when agent integration is unavailable or for platforms without agent support

### How Authentication Works

When you run `spec <ticket-id>`, SPEC uses the AUTO fetch strategy:

1. **First**, tries Auggie MCP integration (if available for the platform)
2. **If unavailable**, falls back to direct API access using your configured credentials

For Azure DevOps, Monday, and Trello, SPEC always uses direct API access since these platforms don't have Auggie MCP integration.

---

## Quick Reference Table

| Platform | Auggie Support | Fallback Required | Config Keys |
|----------|---------------|-------------------|-------------|
| Jira | ✅ Primary | Optional | `FALLBACK_JIRA_URL`, `FALLBACK_JIRA_EMAIL`, `FALLBACK_JIRA_TOKEN` |
| Linear | ✅ Primary | Optional | `FALLBACK_LINEAR_API_KEY` |
| GitHub | ✅ Primary | Optional | `FALLBACK_GITHUB_TOKEN` |
| Azure DevOps | ❌ | **Required** | `FALLBACK_AZURE_DEVOPS_ORGANIZATION`, `FALLBACK_AZURE_DEVOPS_PAT` |
| Monday | ❌ | **Required** | `FALLBACK_MONDAY_API_KEY` |
| Trello | ❌ | **Required** | `FALLBACK_TRELLO_API_KEY`, `FALLBACK_TRELLO_TOKEN` |

---

## Credential Key Aliases

For convenience, SPEC accepts alternative key names that are automatically normalized to canonical keys:

| Platform | Alias | Canonical Key |
|----------|-------|---------------|
| Azure DevOps | `org` | `organization` |
| Azure DevOps | `token` | `pat` |
| Jira | `base_url` | `url` |
| Trello | `api_token` | `token` |

**Example:** `FALLBACK_AZURE_DEVOPS_ORG=myorg` is equivalent to `FALLBACK_AZURE_DEVOPS_ORGANIZATION=myorg`

---

## Configuration File Locations & Precedence

SPEC supports multiple configuration files with a cascading hierarchy. Settings from higher-priority sources override lower-priority ones.

### Configuration Precedence (Highest to Lowest)

| Priority | Source | Location | Use Case |
|----------|--------|----------|----------|
| 1 (Highest) | Environment Variables | Shell environment | CI/CD, temporary overrides |
| 2 | Local Config | `.spec` in project directory | Project-specific settings |
| 3 | Global Config | `~/.spec-config` | User defaults |
| 4 (Lowest) | Built-in Defaults | Hardcoded in SPEC | Non-secret defaults only (e.g., default platform) |

> **Note:** Built-in defaults apply only to non-secret settings like `DEFAULT_PLATFORM`. Credentials have no defaults—you must provide them explicitly.

### Local Config (`.spec`)

SPEC searches upward from the current directory for a `.spec` file. This allows project-specific configuration that overrides global settings.

**Example project structure:**
```
my-project/
├── .spec           ← Project-specific config (if needed)
└── src/
    └── ...
```

**Use cases for local config:**
- Team-shared non-secret settings (e.g., default platform, fetch strategy)
- Project-specific default platform
- CI/CD settings for a particular repository

> **⚠️ Security Warning:** Never commit secrets or credentials to a `.spec` file if it is tracked in version control. Use environment variables for secrets (see [Security Best Practices](#security-best-practices)). If your `.spec` file contains personal credentials, add it to `.gitignore`.

```bash
# Add to your .gitignore
.spec
```

### Global Config (`~/.spec-config`)

The global config file stores user-wide defaults. This is the recommended location for personal credentials and preferences.

**Location:** `~/.spec-config` (in your home directory)

### Viewing Current Configuration

Use `spec --config` to see your current configuration:

```bash
spec --config
```

This displays:
- Active configuration file locations
- Current settings and their sources
- Which platforms are configured

---

## Setting Default Platform

Configure a default platform to avoid specifying `--platform` on every command.

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

---

## Platforms with Auggie Integration

These platforms work out-of-the-box when using Auggie. Fallback credentials are optional but recommended for CI/CD environments or as a backup.

### Jira

Jira is fully integrated with Auggie's MCP tools. When using Auggie, no additional configuration is needed.

#### Supported Input Formats

| Format | Example |
|--------|---------|
| Atlassian Cloud URL | `https://company.atlassian.net/browse/PROJ-123` |
| Self-hosted URL | `https://jira.company.com/browse/PROJ-123` |
| Ticket ID | `PROJ-123` |

#### Optional Fallback Credentials

| Config Key | Description |
|------------|-------------|
| `FALLBACK_JIRA_URL` | Your Jira instance URL (e.g., `https://company.atlassian.net`) |
| `FALLBACK_JIRA_EMAIL` | Your Atlassian account email |
| `FALLBACK_JIRA_TOKEN` | API token (not your password) |

#### Getting an API Token

1. Go to [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Click **"Create API token"**
3. Give it a descriptive name (e.g., "SPEC CLI")
4. Copy the token immediately (it won't be shown again)
5. Store it in an environment variable:
   ```bash
   export JIRA_API_TOKEN="your-token-here"
   ```

#### Configuration

```bash
# ~/.spec-config
FALLBACK_JIRA_URL=https://company.atlassian.net
FALLBACK_JIRA_EMAIL=user@example.com
FALLBACK_JIRA_TOKEN=${JIRA_API_TOKEN}
```

> **Note:** For Jira Server/Data Center, use your instance URL instead of `atlassian.net`.

**Official Documentation:** [Jira REST API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/)

---

### Linear

Linear is fully integrated with Auggie's MCP tools. When using Auggie, no additional configuration is needed.

#### Supported Input Formats

| Format | Example |
|--------|---------|
| Linear URL | `https://linear.app/team/issue/ENG-456` |
| Ticket ID | `ENG-456` ⚠️ (ambiguous with Jira—use URL or `--platform linear`) |

> **Note:** Ticket IDs like `ENG-456` match both Linear and Jira formats. Use the full URL or pass `--platform linear` to avoid ambiguity.

#### Optional Fallback Credentials

| Config Key | Description |
|------------|-------------|
| `FALLBACK_LINEAR_API_KEY` | Personal API key |

#### Getting an API Key

1. Go to [Linear Settings → API](https://linear.app/settings/api)
2. Under **"Personal API keys"**, click **"Create key"**
3. Give it a label (e.g., "SPEC CLI")
4. Copy the key immediately
5. Store it in an environment variable:
   ```bash
   export LINEAR_API_KEY="lin_api_xxxxxxxxxxxx"
   ```

#### Configuration

```bash
# ~/.spec-config
FALLBACK_LINEAR_API_KEY=${LINEAR_API_KEY}
```

> **Note:** API keys have access to all workspaces your account can access.

**Official Documentation:** [Linear GraphQL API](https://developers.linear.app/docs/graphql/working-with-the-graphql-api)

---

### GitHub

GitHub Issues is fully integrated with Auggie's MCP tools. When using Auggie, no additional configuration is needed.

#### Supported Input Formats

| Format | Example |
|--------|---------|
| Issue URL | `https://github.com/owner/repo/issues/42` |
| Pull Request URL | `https://github.com/owner/repo/pull/42` |
| Short reference | `owner/repo#42` |

#### Optional Fallback Credentials

| Config Key | Description |
|------------|-------------|
| `FALLBACK_GITHUB_TOKEN` | Personal access token |

#### Getting a Personal Access Token

1. Go to [GitHub Settings → Developer settings → Personal access tokens](https://github.com/settings/tokens)
2. Choose **"Fine-grained tokens"** (recommended) or **"Tokens (classic)"**

**For Fine-grained tokens:**
- Set an expiration date
- Select the repositories you need access to
- Under **"Repository permissions"**, enable:
  - **Issues:** Read
  - **Pull requests:** Read (if fetching PR-related issues)

**For Classic tokens:**
- Select scopes:
  - `repo` (full repository access) or `public_repo` (public repositories only)

3. Generate and copy the token
4. Store it in an environment variable:
   ```bash
   export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
   ```

#### Configuration

```bash
# ~/.spec-config
FALLBACK_GITHUB_TOKEN=${GITHUB_TOKEN}
```

**Official Documentation:** [GitHub REST API - Issues](https://docs.github.com/en/rest/issues)

---

## Platforms Requiring Fallback Credentials

These platforms do not have Auggie MCP integration. You **must** configure fallback credentials to use them.

### Azure DevOps

Azure DevOps requires fallback credentials—there is no Auggie MCP integration.

#### Supported Input Formats

| Format | Example |
|--------|---------|
| dev.azure.com URL | `https://dev.azure.com/org/project/_workitems/edit/123` |
| visualstudio.com URL | `https://org.visualstudio.com/project/_workitems/edit/123` |
| Work Item ID | `AB#123` |

#### Required Credentials

| Config Key | Description |
|------------|-------------|
| `FALLBACK_AZURE_DEVOPS_ORGANIZATION` | Your Azure DevOps organization name |
| `FALLBACK_AZURE_DEVOPS_PAT` | Personal Access Token |

#### Getting a Personal Access Token (PAT)

1. Sign in to [Azure DevOps](https://dev.azure.com/)
2. Click your profile icon (top right) → **"Personal access tokens"**
3. Click **"New Token"**
4. Configure the token:
   - **Name:** SPEC CLI
   - **Organization:** Select your organization (or "All accessible organizations")
   - **Expiration:** Set an appropriate date (max 1 year)
   - **Scopes:** Select **"Custom defined"**, then enable:
     - **Work Items:** Read
5. Click **"Create"** and copy the token immediately
6. Store it in an environment variable:
   ```bash
   export AZURE_DEVOPS_PAT="your-pat-here"
   ```

#### Configuration

```bash
# ~/.spec-config
FALLBACK_AZURE_DEVOPS_ORGANIZATION=myorg
FALLBACK_AZURE_DEVOPS_PAT=${AZURE_DEVOPS_PAT}
```

> **⚠️ Important:** PATs expire! Set a calendar reminder to rotate your token before it expires. Maximum expiration is 1 year.

**Official Documentation:** [Azure DevOps REST API](https://learn.microsoft.com/en-us/rest/api/azure/devops/)

---

### Monday.com

Monday.com requires fallback credentials—there is no Auggie MCP integration.

#### Supported Input Formats

| Format | Example |
|--------|---------|
| Board/Pulse URL | `https://mycompany.monday.com/boards/123456/pulses/789` |
| View URL | `https://view.monday.com/boards/123456/pulses/789` |

> **Note:** Monday.com does not support standalone item IDs—you must use the full URL.

#### Required Credentials

| Config Key | Description |
|------------|-------------|
| `FALLBACK_MONDAY_API_KEY` | API v2 token |

#### Getting an API Token

1. Sign in to [monday.com](https://monday.com/)
2. Click your profile avatar (bottom left) → **"Administration"**
3. Go to **"Connections"** → **"API"**
4. Copy your **API v2 Token** (or generate a new one)
5. Store it in an environment variable:
   ```bash
   export MONDAY_API_KEY="your-api-key-here"
   ```

#### Configuration

```bash
# ~/.spec-config
FALLBACK_MONDAY_API_KEY=${MONDAY_API_KEY}
```

> **Note:** The API token has access to all boards your account can access.

**Official Documentation:** [Monday.com API](https://developer.monday.com/api-reference/docs)

---

### Trello

Trello requires fallback credentials—there is no Auggie MCP integration.

#### Supported Input Formats

| Format | Example |
|--------|---------|
| Card URL | `https://trello.com/c/aBcDeFgH/123-card-title` |
| Short URL | `https://trello.com/c/aBcDeFgH` |
| Short link ID | `aBcDeFgH` (8 alphanumeric characters) |

#### Required Credentials

| Config Key | Trello Official Term | Description |
|------------|---------------------|-------------|
| `FALLBACK_TRELLO_API_KEY` | **API Key** | Your Trello API Key from the Power-Up Admin portal |
| `FALLBACK_TRELLO_TOKEN` | **Token** | Authorization Token generated for your account |

> **Terminology Note:** Trello's official terms are "API Key" and "Token". SPEC also accepts `api_token` as an alias for `token` (see [Credential Key Aliases](#credential-key-aliases)).

#### Getting Credentials (Two-Step Process)

**Step 1: Get your API Key**

1. Go to [Trello Power-Up Admin](https://trello.com/power-ups/admin)
2. Click **"New"** to create a new Power-Up (or use an existing one)
3. Copy your **API Key** — this is the value for `FALLBACK_TRELLO_API_KEY`

**Step 2: Generate a Token**

1. Visit this URL (replace `YOUR_API_KEY` with the API Key from Step 1):
   ```
   https://trello.com/1/authorize?expiration=never&scope=read&response_type=token&key=YOUR_API_KEY
   ```
2. Click **"Allow"** to authorize
3. Copy the **Token** displayed — this is the value for `FALLBACK_TRELLO_TOKEN`
4. Store both in environment variables:
   ```bash
   export TRELLO_API_KEY="your-api-key-here"
   export TRELLO_TOKEN="your-token-here"
   ```

#### Configuration

```bash
# ~/.spec-config
FALLBACK_TRELLO_API_KEY=${TRELLO_API_KEY}
FALLBACK_TRELLO_TOKEN=${TRELLO_TOKEN}
```

> **Note:** The token generated with `expiration=never` does not expire. For better security, you can set `expiration=30days` or another duration.

**Official Documentation:** [Trello REST API](https://developer.atlassian.com/cloud/trello/)

---

## Complete Configuration Example

Here's a complete example `~/.spec-config` file:

```bash
# ~/.spec-config

# ============================================================
# DEFAULT PLATFORM (optional - avoids --platform flag)
# ============================================================
DEFAULT_PLATFORM=jira

# ============================================================
# AGENT CONFIGURATION (for Auggie users)
# ============================================================
AGENT_PLATFORM=auggie
AGENT_INTEGRATION_JIRA=true
AGENT_INTEGRATION_LINEAR=true
AGENT_INTEGRATION_GITHUB=true
AGENT_INTEGRATION_AZURE_DEVOPS=false
AGENT_INTEGRATION_TRELLO=false
AGENT_INTEGRATION_MONDAY=false

# ============================================================
# FALLBACK CREDENTIALS
# ============================================================

# --- Azure DevOps (REQUIRED - no Auggie integration) ---
FALLBACK_AZURE_DEVOPS_ORGANIZATION=myorg
FALLBACK_AZURE_DEVOPS_PAT=${AZURE_DEVOPS_PAT}

# --- Trello (REQUIRED - no Auggie integration) ---
FALLBACK_TRELLO_API_KEY=${TRELLO_API_KEY}
FALLBACK_TRELLO_TOKEN=${TRELLO_TOKEN}

# --- Monday (REQUIRED - no Auggie integration) ---
FALLBACK_MONDAY_API_KEY=${MONDAY_API_KEY}

# --- Jira (OPTIONAL - for fallback when Auggie unavailable) ---
# FALLBACK_JIRA_URL=https://company.atlassian.net
# FALLBACK_JIRA_EMAIL=user@example.com
# FALLBACK_JIRA_TOKEN=${JIRA_API_TOKEN}

# --- Linear (OPTIONAL - for fallback when Auggie unavailable) ---
# FALLBACK_LINEAR_API_KEY=${LINEAR_API_KEY}

# --- GitHub (OPTIONAL - for fallback when Auggie unavailable) ---
# FALLBACK_GITHUB_TOKEN=${GITHUB_TOKEN}
```

---

## Security Best Practices

### Never Hardcode Secrets

**❌ Don't do this:**
```bash
FALLBACK_JIRA_TOKEN=abc123secrettoken
```

**✅ Do this instead:**
```bash
FALLBACK_JIRA_TOKEN=${JIRA_API_TOKEN}
```

### Environment Variable Syntax

Use `${VAR_NAME}` syntax to reference environment variables in your config file. SPEC expands these at runtime.

### Setting Environment Variables

Add exports to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.bash_profile`):

```bash
# Add to ~/.zshrc or ~/.bashrc
export JIRA_API_TOKEN="your-jira-token"
export LINEAR_API_KEY="your-linear-key"
export GITHUB_TOKEN="your-github-token"
export AZURE_DEVOPS_PAT="your-azure-pat"
export MONDAY_API_KEY="your-monday-key"
export TRELLO_API_KEY="your-trello-api-key"
export TRELLO_TOKEN="your-trello-token"
```

Then reload your shell:
```bash
source ~/.zshrc  # or ~/.bashrc
```

### CI/CD Environments

For CI/CD pipelines, use your platform's secret management:

- **GitHub Actions:** Use [encrypted secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- **GitLab CI:** Use [CI/CD variables](https://docs.gitlab.com/ee/ci/variables/)
- **Jenkins:** Use [credentials plugin](https://plugins.jenkins.io/credentials/)
- **Azure Pipelines:** Use [secret variables](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/variables#secret-variables)

### Token Rotation

API tokens should be rotated periodically for security. Here's a recommended schedule:

| Platform | Max Token Lifetime | Recommended Rotation |
|----------|-------------------|---------------------|
| Jira | No expiration | Every 90 days |
| Linear | No expiration | Every 90 days |
| GitHub | Configurable (fine-grained) or no expiration (classic) | Every 90 days |
| Azure DevOps | 1 year max | Before expiration |
| Monday | No expiration | Every 90 days |
| Trello | Configurable (`expiration` param) | Every 90 days |

**Rotation process:**
1. Generate a new token in the platform's admin console
2. Update the environment variable in your shell profile
3. Reload your shell (`source ~/.zshrc`)
4. Verify with `spec --config`
5. Revoke the old token in the platform's admin console

### Scoping Tokens

Follow the principle of least privilege:

- **Jira:** Grant access only to required projects
- **GitHub:** Use fine-grained tokens scoped to specific repositories
- **Azure DevOps:** Scope to specific organizations/projects if possible
- **Linear/Monday/Trello:** Account-level tokens typically required

---

## Verifying Your Configuration

### Check Configuration Status

```bash
spec --config
```

This displays:
- Which platforms are configured
- Default platform setting
- Agent integration status
- Fallback credential status (configured/not configured)

### Test with a Real Ticket

```bash
# Test Jira
spec PROJ-123

# Test Linear
spec --platform linear ABC-123

# Test GitHub
spec --platform github owner/repo#42

# Test Azure DevOps
spec --platform azure_devops https://dev.azure.com/org/project/_workitems/edit/123
```

### Expected Success Output

When configuration is correct, you'll see the ticket content rendered as a specification document.

---

## Troubleshooting

### Common Errors

| Error Message | Cause | Solution |
|---------------|-------|----------|
| `No fallback credentials configured for platform 'X'` | Missing `FALLBACK_*` keys | Add required credentials to `~/.spec-config` |
| `Missing required credential fields for 'X': field1, field2` | Incomplete credentials | Add the listed fields to your config |
| `Credential field 'X' for 'Y' is empty` | Empty credential value | Provide a non-empty value for the field |
| `Credential field 'X' for 'Y' contains unexpanded environment variable: ${VAR}` | Environment variable not set | Set the environment variable in your shell |
| `401 Unauthorized` | Invalid or expired token | Regenerate your API token |
| `403 Forbidden` | Insufficient permissions | Check token scopes/permissions |
| `Connection timeout` | Network issue | Check internet connection and firewall |

### Debugging Tips

1. **Check environment variables are set:**
   ```bash
   echo $JIRA_API_TOKEN
   ```

2. **Verify config file syntax:**
   ```bash
   cat ~/.spec-config
   ```

3. **Test API access directly:**
   ```bash
   # Example: Test Jira API
   curl -u "email@example.com:$JIRA_API_TOKEN" \
     "https://company.atlassian.net/rest/api/3/myself"
   ```

### Ambiguous Ticket IDs

Ticket IDs like `ABC-123` match both Jira and Linear formats. When SPEC cannot determine the platform:

1. It checks `DEFAULT_PLATFORM` in `~/.spec-config`
2. If not set, it prompts you to select a platform interactively

**Solutions:**

```bash
# Option 1: Use --platform flag
spec ENG-456 --platform linear

# Option 2: Set a default platform
echo 'DEFAULT_PLATFORM=jira' >> ~/.spec-config

# Option 3: Use full URLs (always unambiguous)
spec https://linear.app/team/issue/ENG-456
```

### Platform-Specific Issues

**Jira:**
- Ensure you're using an API token, not your password
- Cloud vs Server/Data Center may have different URL formats

**GitHub:**
- Fine-grained tokens require explicit repository access
- Classic tokens with `repo` scope work for all repositories

**Azure DevOps:**
- PAT must have "Work Items: Read" scope
- Organization name is case-sensitive

**Monday:**
- Only URL-based access is supported (no standalone item IDs)
- URL format: `https://<subdomain>.monday.com/boards/<board_id>/pulses/<item_id>`

**Trello:**
- Both API key AND token are required
- Token must be authorized for your account

### Getting Help

If you're still having issues:
1. Check the [SPEC README](../README.md) for general usage
2. Review the [configuration template](../spec/config/templates/fetch_config.template) for a complete example with all available options, including fetch strategy, agent integrations, caching, and timeouts
3. Open an issue on the project repository
