/**
 * LLM Provider Configuration
 */

export interface LLMProvider {
    name: string;
    envVar: string;
    prefix: string;
    defaultModel: string;
}

export const PROVIDERS: Record<string, LLMProvider> = {
    gemini: {
        name: 'Gemini',
        envVar: 'GEMINI_API_KEY',
        prefix: 'gemini/',
        defaultModel: 'gemini-3.0-pro-preview'
    },
    openai: {
        name: 'OpenAI',
        envVar: 'OPENAI_API_KEY',
        prefix: 'openai/',
        defaultModel: 'gpt-4o'
    },
    anthropic: {
        name: 'Anthropic',
        envVar: 'ANTHROPIC_API_KEY',
        prefix: 'anthropic/',
        defaultModel: 'claude-3-opus-20240229'
    },
    deepseek: {
        name: 'DeepSeek',
        envVar: 'DEEPSEEK_API_KEY',
        prefix: 'deepseek/',
        defaultModel: 'deepseek-chat'
    }
};

/**
 * Get the provider configuration for a given model string
 * Defaults to Gemini if no matching provider found
 */
export function getProviderFromModel(model: string): LLMProvider {
    // If model has a prefix (e.g. "openai/gpt-4"), use it to find provider
    if (model.includes('/')) {
        const prefix = model.split('/')[0].toLowerCase();
        if (PROVIDERS[prefix]) {
            return PROVIDERS[prefix];
        }
    }

    // Check known model prefixes if no provider prefix is present
    const lowerModel = model.toLowerCase();
    if (lowerModel.startsWith('gpt')) return PROVIDERS.openai;
    if (lowerModel.startsWith('claude')) return PROVIDERS.anthropic;
    if (lowerModel.startsWith('deepseek')) return PROVIDERS.deepseek;

    // Default fallback
    return PROVIDERS.gemini;
}
