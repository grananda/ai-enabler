# Connecting Jira through MCP

The `ai-enabler` pipeline reads tickets, and writes its comment and transition at the ship stage, only through an MCP server. The same holds for the one issue `delivery-ticket-create` creates when asked to. It never calls the Jira REST API itself and never handles credentials.

The plugin does not bundle a Jira server on purpose: which one is right depends on whether the team uses Jira Cloud or Data Center, and bundling one would force its login on everyone who installs the plugin. Pick one of the two options below. The skills find the Jira tools by what they do, so either works without further configuration.

Server packages and endpoints change; check the linked project's own documentation for the current values before copying.

## Option A — Jira Cloud: Atlassian's remote MCP server

Hosted by Atlassian, authenticated with OAuth in the browser. Nothing to install and no token to store.

```
claude mcp add --transport http atlassian https://mcp.atlassian.com/v1/mcp
```

Then run `/mcp` inside Claude Code and complete the login. To share the configuration with the team, add it to the project's `.mcp.json` instead:

```json
{
  "mcpServers": {
    "atlassian": { "type": "http", "url": "https://mcp.atlassian.com/v1/mcp" }
  }
}
```

Each developer authenticates once; what they can read and write is what their Atlassian account can. The same server also covers Confluence, which the ticket analyst uses when a ticket points to a Confluence page for its specification.

## Option B — Jira Data Center or Server: `mcp-atlassian`

A community server that runs locally and talks to a self-hosted Jira with a personal access token. Keep the token in the environment, not in a file that gets committed:

```json
{
  "mcpServers": {
    "jira": {
      "command": "uvx",
      "args": ["mcp-atlassian"],
      "env": {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_PERSONAL_TOKEN": "${JIRA_PERSONAL_TOKEN}"
      }
    }
  }
}
```

Each developer exports `JIRA_PERSONAL_TOKEN` in their shell profile. For Jira Cloud with an API token the same server takes `JIRA_USERNAME` and `JIRA_API_TOKEN` instead. Confluence is configured the same way with the `CONFLUENCE_*` variables.

To make the pipeline read-only towards Jira regardless of configuration, start the server in its read-only mode (see its documentation); the ship stage will then report that the comment and transition were skipped.

## Checking the connection

```
/ai-enabler:delivery-doctor PROJ-123
```

reports which server provides the Jira tools, fetches the ticket as proof that reading works, and says whether tools for commenting and transitioning are available.

With more than one Jira server connected, the pipeline asks once which to use; set `jira.server` in `.enabler/config.json` to make the choice permanent.

## What the pipeline does with Jira

| When | Action | Controlled by |
|---|---|---|
| Intake | Reads the issue, its comments, and the links needed to understand it | always |
| Ship | Adds a comment with the branch, the pull-request link, the result and open items | `jira.comment_on_ship` (default on) |
| Ship | Transitions the issue | `jira.transition_on_ship` (default off) |

Writes happen only after the ship gate, which lists them. The pipeline never edits the description or the acceptance criteria, never reassigns, and never deletes an issue.

## Permissions

The first use of each MCP tool raises a permission prompt. To avoid being asked on every run, allow the read tools in the project's `.claude/settings.json`, using the tool names shown by `/mcp` for your server, for example:

```json
{ "permissions": { "allow": ["mcp__atlassian__getJiraIssue", "mcp__atlassian__searchJiraIssuesUsingJql"] } }
```

Leave the write tools on "ask" unless the team is comfortable with the ship gate being the only confirmation. Permission prompts are counted by `ai-enabler-metrics` as human interactions, so tuning these rules shows up directly in the usage report.

## No Jira at all

Pass a Markdown file instead of a key:

```
/ai-enabler:delivery-run docs/requirements/export-csv.md
```

The file should state the requirements and, ideally, the acceptance criteria. The pipeline runs unchanged, minus the Jira update.
