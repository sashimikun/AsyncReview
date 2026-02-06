/**
 * LLM Provider Configuration
 */

export interface LLMProvider {
    name: string;
    envVar: string;
    prefix: string;
    defaultModel: string;
    matches?: (model: string) => boolean;
}

export const PROVIDERS: Record<string, LLMProvider> = {
    gemini: {
        name: 'Gemini',
        envVar: 'GEMINI_API_KEY',
        prefix: 'gemini/',
        defaultModel: 'gemini-1.5-pro',
        matches: (model) => model.startsWith('gemini')
    },
    openai: {
        name: 'OpenAI',
        envVar: 'OPENAI_API_KEY',
        prefix: 'openai/',
        defaultModel: 'gpt-4o',
        matches: (model) => model.startsWith('gpt') || model.startsWith('o1')
    },
    anthropic: {
        name: 'Anthropic',
        envVar: 'ANTHROPIC_API_KEY',
        prefix: 'anthropic/',
        defaultModel: 'claude-3-opus-20240229',
        matches: (model) => model.startsWith('claude')
    },
    deepseek: {
        name: 'DeepSeek',
        envVar: 'DEEPSEEK_API_KEY',
        prefix: 'deepseek/',
        defaultModel: 'deepseek-chat',
        matches: (model) => model.startsWith('deepseek')
    }
};

/**
 * Get the provider configuration for a given model string
 * Throws an error if no provider can be inferred
 */
export function getProviderFromModel(model: string): LLMProvider {
    // 1. Check explicit prefix (e.g. "openai/gpt-4")
    if (model.includes('/')) {
        const prefix = model.split('/')[0].toLowerCase();
        if (PROVIDERS[prefix]) {
            return PROVIDERS[prefix];
        }
        throw new Error(`Unknown LLM provider prefix: '${prefix}'. Supported: ${Object.keys(PROVIDERS).join(', ')}`);
    }

    // 2. Check heuristics
    const lowerModel = model.toLowerCase();
    for (const key in PROVIDERS) {
        if (PROVIDERS[key].matches?.(lowerModel)) {
            return PROVIDERS[key];
        }
    }

    // 3. Fail safe instead of defaulting
    throw new Error(`Could not infer provider for model '${model}'. Please use the format 'provider/model' (e.g. 'anthropic/claude-3').`);
}

/**
 * Normalize a model name and return its provider configuration
 * Handles default model logic, provider inference, and canonical name construction
 */
export function normalizeModelName(model: string | undefined): { provider: LLMProvider, canonicalName: string } {
    // Handle default case
    if (!model) {
        const provider = PROVIDERS.gemini;
        return {
            provider,
            canonicalName: provider.defaultModel.includes('/')
                ? provider.defaultModel
                : `${provider.prefix}${provider.defaultModel}`
        };
    }

    const provider = getProviderFromModel(model);
    let canonicalName = model;

    if (model.includes('/')) {
        // Normalize prefix case (e.g. OpenAI/gpt -> openai/gpt)
        const [prefix, ...rest] = model.split('/');
        canonicalName = `${prefix.toLowerCase()}/${rest.join('/')}`;
    } else {
        // Add missing prefix
        canonicalName = `${provider.prefix}${model}`;
    }

    return { provider, canonicalName };
}
