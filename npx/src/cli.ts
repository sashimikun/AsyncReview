/**
 * Main CLI handler for the review command
 */

import chalk from 'chalk';
import ora from 'ora';
import { getApiKey, getGitHubToken } from './api-key.js';
import { getProviderFromModel, PROVIDERS } from './llm-config.js';
import {
    checkPython,
    checkDeno,
    installDeno,
    checkAsyncReviewInstalled,
    installAsyncReview,
    runPythonReview
} from './python-runner.js';

export interface ReviewOptions {
    url: string;
    question?: string;
    output: string;
    quiet?: boolean;
    model?: string;
    api?: string;
    githubToken?: string;
    expert?: boolean;
}

export async function runReview(options: ReviewOptions): Promise<void> {
    const { url, question, output, quiet = false, model, api, githubToken, expert = false } = options;

    try {
        // Determine provider and model
        const resolvedModel = model || PROVIDERS.gemini.defaultModel;
        const provider = getProviderFromModel(resolvedModel);

        // Ensure model string passed to Python has the provider prefix if needed
        let modelToPass = model;
        if (model && !model.includes('/')) {
            modelToPass = `${provider.prefix}${model}`;
        }

        // 4. Get API key
        const apiKey = await getApiKey(api, provider);

        // 5. Get GitHub token (required for code search API)
        const ghToken = await getGitHubToken(githubToken, true);

        // 6. Run the review
        if (!quiet) {
            console.log(chalk.cyan(`\n 🔍 Reviewing: ${url}`));
            if (expert) {
                console.log(chalk.cyan(`   Mode: Expert Code Review (SOLID, Security, Code Quality)\n`));
            } else if (question) {
                console.log(chalk.dim(`   Question: ${question}\n`));
            }
        }

        const result = await runPythonReview({
            url,
            question,
            output,
            quiet,
            model: modelToPass,
            apiKey,
            providerEnvVar: provider.envVar,
            githubToken: ghToken,
            expert,
        });

        // In quiet mode, we suppressed stdout during execution
        // So we must print the final result now
        if (quiet && result.trim()) {
            console.log(result);
        }

    } catch (error) {
        if (error instanceof Error) {
            console.error(chalk.red(`\nError: ${error.message}`));
        } else {
            console.error(chalk.red('\nAn unexpected error occurred'));
        }
        process.exit(1);
    }
}
