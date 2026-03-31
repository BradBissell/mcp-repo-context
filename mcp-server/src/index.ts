#!/usr/bin/env node

/**
 * Review Knowledge MCP Server
 * Queries ChromaDB review comment and codebase knowledge base via Python bridge.
 *
 * Environment variables:
 *   REVIEW_QUERY_SCRIPT_PATH  - path to query-review-knowledge.py
 *   CODEBASE_QUERY_SCRIPT_PATH - path to query-codebase.py
 *   CHROMA_DB_PATH            - path to ChromaDB storage directory
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const execFileAsync = promisify(execFile);

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCRIPTS_DIR = resolve(__dirname, '..', '..');

const REVIEW_QUERY_SCRIPT = process.env.REVIEW_QUERY_SCRIPT_PATH
  || resolve(SCRIPTS_DIR, 'query-review-knowledge.py');
const CODEBASE_QUERY_SCRIPT = process.env.CODEBASE_QUERY_SCRIPT_PATH
  || resolve(SCRIPTS_DIR, 'query-codebase.py');

async function queryScript(script: string, args: Record<string, unknown>): Promise<unknown> {
  const { stdout } = await execFileAsync('python3', [script, JSON.stringify(args)], {
    timeout: 30000,
    env: { ...process.env },
  });
  return JSON.parse(stdout);
}

const queryReviews = (args: Record<string, unknown>) => queryScript(REVIEW_QUERY_SCRIPT, args);
const queryCodebase = (args: Record<string, unknown>) => queryScript(CODEBASE_QUERY_SCRIPT, args);

const server = new Server(
  { name: 'review-knowledge-server', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'search_similar_reviews',
      description:
        'Semantic search across past PR review comments from BradBissell. ' +
        'Use to find similar feedback, patterns, or past decisions. ' +
        'Returns comments ranked by relevance with file paths, tickets, and diff context.',
      inputSchema: {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'Natural language search query (e.g., "error handling patterns", "naming conventions for services")',
          },
          file_path_pattern: {
            type: 'string',
            description: 'Filter to files containing this string (e.g., ".controller.ts", "auth/")',
          },
          ticket: {
            type: 'string',
            description: 'Filter to a specific JIRA ticket (e.g., "DR-8062")',
          },
          comment_type: {
            type: 'string',
            enum: ['inline_comment', 'review_body'],
            description: 'Filter by comment type: inline_comment (on specific code lines) or review_body (PR-level summary)',
          },
          pr_number: {
            type: 'number',
            description: 'Filter to a specific PR number',
          },
          limit: {
            type: 'number',
            description: 'Max results to return (default: 5, max: 20)',
          },
        },
        required: ['query'],
      },
    },
    {
      name: 'get_review_patterns_for_file',
      description:
        'Find past review comments related to a specific file or file type. ' +
        'Combines exact file matches, semantic similarity, and extension-based pattern matching. ' +
        'Use before reviewing a file to understand what feedback has been given on similar code.',
      inputSchema: {
        type: 'object',
        properties: {
          file_path: {
            type: 'string',
            description: 'File path to find review patterns for (e.g., "applications/api/src/auth/auth.controller.ts")',
          },
          limit: {
            type: 'number',
            description: 'Max results to return (default: 10)',
          },
        },
        required: ['file_path'],
      },
    },
    {
      name: 'get_ticket_review_history',
      description:
        'Get all review comments for a specific JIRA ticket, sorted chronologically. ' +
        'Use to understand the full review feedback history for a ticket before working on related code.',
      inputSchema: {
        type: 'object',
        properties: {
          ticket: {
            type: 'string',
            description: 'JIRA ticket number (e.g., "DR-8062")',
          },
        },
        required: ['ticket'],
      },
    },
    {
      name: 'search_codebase',
      description:
        'Semantic search across the aim-myt codebase (functions, classes, types, components). ' +
        'Use to find code by natural language description (e.g., "authentication guard", "cart checkout logic", "listing composable").',
      inputSchema: {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'Natural language search query describing the code you want to find',
          },
          module: {
            type: 'string',
            description: 'Filter to a specific module (e.g., "auth", "messages", "components/cart")',
          },
          application: {
            type: 'string',
            enum: ['api', 'ui'],
            description: 'Filter to API or UI application',
          },
          file_type: {
            type: 'string',
            enum: ['source', 'test'],
            description: 'Filter to source code or test files',
          },
          chunk_type: {
            type: 'string',
            enum: ['class', 'function', 'type', 'constant', 'template', 'file'],
            description: 'Filter by chunk type',
          },
          language: {
            type: 'string',
            enum: ['typescript', 'vue', 'javascript'],
            description: 'Filter by language',
          },
          file_path_pattern: {
            type: 'string',
            description: 'Filter to files containing this string (e.g., ".controller.ts", "auth/")',
          },
          limit: {
            type: 'number',
            description: 'Max results to return (default: 5, max: 20)',
          },
        },
        required: ['query'],
      },
    },
    {
      name: 'get_file_chunks',
      description:
        'Get all code chunks (functions, classes, types) for a specific file. ' +
        'Use to understand the structure and contents of a file.',
      inputSchema: {
        type: 'object',
        properties: {
          file_path: {
            type: 'string',
            description: 'Exact file path (e.g., "applications/api/src/auth/auth.service.ts")',
          },
        },
        required: ['file_path'],
      },
    },
    {
      name: 'get_module_overview',
      description:
        'List all code chunks in a module to understand its structure. ' +
        'Returns functions, classes, types, and components organized by file.',
      inputSchema: {
        type: 'object',
        properties: {
          module: {
            type: 'string',
            description: 'Module name (e.g., "auth", "messages", "components/cart", "stores")',
          },
          application: {
            type: 'string',
            enum: ['api', 'ui'],
            description: 'Filter to API or UI application',
          },
        },
        required: ['module'],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args = {} } = request.params;

  try {
    let chromaArgs: Record<string, unknown>;
    let result: unknown;

    switch (name) {
      case 'search_similar_reviews':
        chromaArgs = {
          command: 'search',
          query: args.query,
          file_path_pattern: args.file_path_pattern,
          ticket: args.ticket,
          comment_type: args.comment_type,
          pr_number: args.pr_number,
          limit: Math.min((args.limit as number) || 5, 20),
        };
        result = await queryReviews(chromaArgs);
        break;

      case 'get_review_patterns_for_file':
        chromaArgs = {
          command: 'patterns',
          file_path: args.file_path,
          limit: (args.limit as number) || 10,
        };
        result = await queryReviews(chromaArgs);
        break;

      case 'get_ticket_review_history':
        chromaArgs = {
          command: 'history',
          ticket: args.ticket,
        };
        result = await queryReviews(chromaArgs);
        break;

      case 'search_codebase':
        chromaArgs = {
          command: 'search',
          query: args.query,
          module: args.module,
          application: args.application,
          file_type: args.file_type,
          chunk_type: args.chunk_type,
          language: args.language,
          file_path_pattern: args.file_path_pattern,
          limit: Math.min((args.limit as number) || 5, 20),
        };
        result = await queryCodebase(chromaArgs);
        break;

      case 'get_file_chunks':
        chromaArgs = {
          command: 'file_chunks',
          file_path: args.file_path,
        };
        result = await queryCodebase(chromaArgs);
        break;

      case 'get_module_overview':
        chromaArgs = {
          command: 'module_overview',
          module: args.module,
          application: args.application,
        };
        result = await queryCodebase(chromaArgs);
        break;

      default:
        return {
          content: [{ type: 'text', text: JSON.stringify({ error: `Unknown tool: ${name}` }) }],
          isError: true,
        };
    }

    return {
      content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return {
      content: [{ type: 'text', text: JSON.stringify({ error: message }) }],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('Review Knowledge MCP Server running on stdio');
  console.error(`Review script: ${REVIEW_QUERY_SCRIPT}`);
  console.error(`Codebase script: ${CODEBASE_QUERY_SCRIPT}`);
}

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
