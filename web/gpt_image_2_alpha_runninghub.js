import { app } from "../../scripts/app.js";

const TARGET_NODE = "RunningHubGptImage2Alpha_TBatch";
const CANCEL_WIDGET_NAME = "取消轮询";

function addCancelWidget(node) {
    if (!node || node.widgets?.find((widget) => widget.name === CANCEL_WIDGET_NAME)) return;

    const button = node.addWidget("button", CANCEL_WIDGET_NAME, null, () => {
        button.value = "已发送中断信号";
        fetch("/synvow-prompt/rh-gpt-image2-alpha/cancel", { method: "POST" }).catch((error) => {
            console.error("[SynVow-prompt] RH GPT-Image-2 Alpha cancel failed:", error);
        });
        fetch("/interrupt", { method: "POST" }).catch((error) => {
            console.error("[SynVow-prompt] ComfyUI interrupt failed:", error);
        });
        setTimeout(() => {
            button.value = CANCEL_WIDGET_NAME;
        }, 3000);
    });
    button.serialize = false;
}

app.registerExtension({
    name: "SynVowPrompt.RHGptImage2Alpha",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== TARGET_NODE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            setTimeout(() => addCancelWidget(this), 0);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            setTimeout(() => addCancelWidget(this), 0);
            return result;
        };
    },

    async setup() {
        setTimeout(() => {
            for (const node of app.graph?._nodes || []) {
                if (node.type === TARGET_NODE) addCancelWidget(node);
            }
        }, 500);
    },
});
