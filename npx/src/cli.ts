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
        let provider;
        try {
            provider = getProviderFromModel(resolvedModel);
        } catch (e) {
            // If heuristics fail, default to Gemini if it's the default model, otherwise rethrow
            if (resolvedModel === PROVIDERS.gemini.defaultModel) {
                provider = PROVIDERS.gemini;
            } else {
                throw e;
            }
        }

        // Ensure model string passed to Python has the provider prefix if needed
        // Use resolvedModel as base if model is undefined to ensure sync with Python
        let modelToPass = model || resolvedModel;

        if (modelToPass.includes('/')) {
            // Normalize prefix case (e.g. OpenAI/gpt -> openai/gpt)
            const [prefix, ...rest] = modelToPass.split('/');
            // Verify prefix exists in PROVIDERS to be safe
            if (PROVIDERS[prefix.toLowerCase()]) {
                 modelToPass = `${prefix.toLowerCase()}/${rest.join('/')}`;
            }
            // If not found, we leave it as is (Python side might handle it or error out,
            // but getProviderFromModel would have thrown already if we used it directly)
        } else {
            modelToPass = `${provider.prefix}${modelToPass}`;
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
