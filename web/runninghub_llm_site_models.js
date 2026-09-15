import { app } from "../../scripts/app.js";

const TARGETS = {
    SynVowTransparentAssetPromptGenerator: {
        siteWidget: "llm_site",
        modelWidget: "model",
        keepOff: false,
    },
    RunningHubGptImage2ProductStudio: {
        siteWidget: "api_base_url",
        modelWidget: "llm_model",
        keepOff: true,
    },
};

const modelCache = new Map();

function widget(node, name) {
    return node.widgets?.find((item) => item.name === name);
}

function siteKey(value) {
    return String(value || "").includes(".ai") ? "ai" : "cn";
}

async function fetchSiteModels(site) {
    if (modelCache.has(site)) return modelCache.get(site);
    const request = fetch(`/synvow-prompt/runninghub-llm-models?site=${encodeURIComponent(site)}&vision=1`)
        .then((response) => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then((data) => ({
            models: Array.isArray(data.models) ? data.models : [],
            defaultModel: String(data.default || ""),
        }));
    modelCache.set(site, request);
    try {
        return await request;
    } catch (error) {
        modelCache.delete(site);
        throw error;
    }
}

function setComboValues(target, values, defaultValue) {
    if (!target || !Array.isArray(values) || values.length === 0) return;
    target.options = target.options || {};
    target.options.values = values;
    if (!values.includes(String(target.value || ""))) {
        target.value = values.includes(defaultValue) ? defaultValue : values[0];
        target.callback?.(target.value);
    }
}

async function refreshNodeModels(node, config) {
    const siteControl = widget(node, config.siteWidget);
    const modelControl = widget(node, config.modelWidget);
    if (!siteControl || !modelControl) return;
    try {
        const site = siteKey(siteControl.value);
        const data = await fetchSiteModels(site);
        const models = [...data.models];
        if (config.keepOff && !models.includes("关闭")) models.push("关闭");
        setComboValues(modelControl, models, data.defaultModel);
        const computed = node.computeSize?.();
        if (computed && node.size) {
            node.setSize?.([Math.max(node.size[0], computed[0]), computed[1]]);
        }
        node.setDirtyCanvas?.(true, true);
    } catch (error) {
        console.warn("[SynVow-prompt] RunningHub model list refresh failed:", error);
    }
}

function enhanceNode(node) {
    const config = TARGETS[node?.type];
    if (!config) return;
    const siteControl = widget(node, config.siteWidget);
    if (!siteControl) return;

    const key = `_synvowSiteModels_${config.siteWidget}`;
    if (!node[key]) {
        const previous = siteControl.callback;
        siteControl.callback = function (value) {
            const result = previous?.apply(this, arguments);
            refreshNodeModels(node, config);
            return result;
        };
        node[key] = true;
    }
    refreshNodeModels(node, config);
}

app.registerExtension({
    name: "SynVowPrompt.RunningHubSiteModels",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGETS[nodeData.name]) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            setTimeout(() => enhanceNode(this), 0);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            setTimeout(() => enhanceNode(this), 0);
            return result;
        };
    },

    async setup() {
        setTimeout(() => {
            for (const node of app.graph?._nodes || []) enhanceNode(node);
        }, 500);
    },
});
