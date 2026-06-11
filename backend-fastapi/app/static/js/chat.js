/**
 * Fund Safety Chat - Continuous conversation interface
 * Handles message sending, display, and conversation history
 */

class ChatSession {
    constructor(scanId, assessment) {
        this.scanId = scanId;
        this.assessment = assessment;
        this.messages = [];
        this.isLoading = false;
        this.init();
    }

    init() {
        this.chatMessages = document.getElementById("chatMessages");
        this.chatInput = document.getElementById("chatInput");
        this.sendBtn = document.getElementById("sendBtn");
        this.clearBtn = document.getElementById("clearBtn");
        this.inputHint = document.getElementById("inputHint");

        // Event listeners
        this.chatInput.addEventListener("keypress", (e) => this.handleKeyPress(e));
        this.chatInput.addEventListener("input", () => this.updateInputState());
        this.sendBtn.addEventListener("click", () => this.sendMessage());
        this.clearBtn.addEventListener("click", () => this.clearChat());

        // Add example questions to click
        this.populateExamples();

        // Enable input and set initial button state
        this.chatInput.disabled = false;
        this.updateInputState();
    }

    populateExamples() {
        const exampleList = document.getElementById("exampleQuestions");
        if (!exampleList) return;

        const examples = EXAMPLE_FUNCTIONS.slice(0, 3);
        if (examples.length === 0) {
            // Add default examples if no functions available
            examples.push(
                "What rules does this scan assess?",
                "Show me critical findings",
                "Which methods are at risk?"
            );
        }

        exampleList.innerHTML = examples
            .map((q) => `<li onclick="window.chat.sendQuestion('${q.replace(/'/g, "\\'")}')">${q}</li>`)
            .join("");
    }

    handleKeyPress(e) {
        if (e.key === "Enter" && !e.shiftKey && !this.isLoading) {
            e.preventDefault();
            this.sendMessage();
        }
    }

    async sendMessage() {
        const question = this.chatInput.value.trim();
        if (!question || this.isLoading) return;

        // Add user message
        this.messages.push({
            role: "user",
            content: question,
        });

        // Clear input and render
        this.chatInput.value = "";
        this.renderMessages();
        this.scrollToBottom();

        // Send to backend
        await this.fetchResponse(question);
    }

    sendQuestion(question) {
        this.chatInput.value = question;
        this.chatInput.focus();
        this.sendMessage();
    }

    async fetchResponse(question) {
        this.isLoading = true;
        this.updateInputState();

        // Show loading indicator
        this.showLoading();

        try {
            const response = await fetch(`/ui/api/chats/${this.scanId}/messages`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({
                    question: question,
                    conversation_history: this.messages.slice(0, -1), // All except the last user message (which was just added)
                }),
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const aiResponse = await response.json();

            // Add AI response
            this.messages.push({
                role: "assistant",
                content: aiResponse.answer || aiResponse.content || "No response",
                query_type: aiResponse.query_type,
                function_name: aiResponse.function_name,
                rule_id: aiResponse.rule_id,
                confidence: aiResponse.confidence || 0,
                requires_clarification: aiResponse.requires_clarification || false,
                candidates: aiResponse.candidates || [],
            });

            // Remove loading and render
            this.removeLoading();
            this.renderMessages();
            this.scrollToBottom();
        } catch (error) {
            console.error("Chat error:", error);
            this.removeLoading();
            this.messages.push({
                role: "assistant",
                content: `Error: ${error.message}. Please try again.`,
                query_type: "error",
            });
            this.renderMessages();
        } finally {
            this.isLoading = false;
            this.updateInputState();
        }
    }

    showLoading() {
        const template = document.getElementById("loadingTemplate");
        const loading = template.content.cloneNode(true);
        this.chatMessages.appendChild(loading);
    }

    removeLoading() {
        const loading = this.chatMessages.querySelector(".message.loading");
        if (loading) loading.remove();
    }

    renderMessages() {
        const container = this.chatMessages;

        // Clear all messages except welcome
        const welcomeMsg = container.querySelector(".welcome-message");
        container.innerHTML = "";

        // Don't show welcome if there are messages
        if (this.messages.length === 0) {
            const template = document.createElement("div");
            template.className = "welcome-message";
            template.innerHTML = `
                <h2>Welcome to Fund Safety Chat</h2>
                <p>Ask questions about this scan's assessment, functions, and safety rules.</p>
                <div class="example-questions">
                    <p><strong>Try asking:</strong></p>
                    <ul id="exampleQuestions"></ul>
                </div>
            `;
            container.appendChild(template);
            this.populateExamples();
            return;
        }

        // Render all messages
        this.messages.forEach((msg) => {
            const messageEl = this.createMessageElement(msg);
            container.appendChild(messageEl);
        });
    }

    createMessageElement(msg) {
        const div = document.createElement("div");
        div.className = `message ${msg.role}-message`;

        if (msg.role === "user") {
            div.innerHTML = `
                <div class="message-content">${this.escapeHtml(msg.content)}</div>
            `;
        } else {
            // AI message
            let headerHtml = "";
            if (msg.query_type) {
                const queryTypeClass = msg.query_type.replace(/_/g, "_");
                const queryTypeLabel = msg.query_type
                    .split("_")
                    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                    .join(" ");

                headerHtml += `<span class="query-type ${queryTypeClass}">${queryTypeLabel}</span>`;
            }

            if (msg.confidence !== undefined && msg.confidence !== null) {
                const confidenceClass = msg.confidence >= 80 ? "high" : msg.confidence >= 50 ? "medium" : "low";
                headerHtml += `<span class="confidence ${confidenceClass}">${msg.confidence}% confidence</span>`;
            }

            let metaHtml = "";
            if (msg.function_name || msg.rule_id) {
                const items = [];
                if (msg.function_name) {
                    items.push(`<span class="meta-item"><span class="meta-icon">ƒ</span>${this.escapeHtml(msg.function_name)}</span>`);
                }
                if (msg.rule_id) {
                    items.push(`<span class="meta-item"><span class="meta-icon">📋</span>${this.escapeHtml(msg.rule_id)}</span>`);
                }
                if (items.length > 0) {
                    metaHtml = `<div class="message-meta">${items.join("")}</div>`;
                }
            }

            // Handle clarification_needed special case
            let contentHtml = this.escapeHtml(msg.content);
            if (msg.requires_clarification && msg.candidates && msg.candidates.length > 0) {
                const candidatesList = msg.candidates.map((c) => `• ${this.escapeHtml(c)}`).join("\n");
                contentHtml += `\n\n${candidatesList}`;
            }

            div.innerHTML = `
                ${headerHtml ? `<div class="message-header">${headerHtml}</div>` : ""}
                <div class="message-content">${contentHtml}</div>
                ${metaHtml}
            `;
        }

        return div;
    }

    scrollToBottom() {
        setTimeout(() => {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }, 0);
    }

    updateInputState() {
        this.chatInput.disabled = this.isLoading;
        this.sendBtn.disabled = this.isLoading || !this.chatInput.value.trim();

        if (this.isLoading) {
            this.inputHint.textContent = "Waiting for response...";
            this.inputHint.classList.add("loading");
        } else {
            this.inputHint.textContent = "";
            this.inputHint.classList.remove("loading");
        }
    }

    clearChat() {
        if (confirm("Clear chat history? This action cannot be undone.")) {
            this.messages = [];
            this.renderMessages();
            this.chatInput.focus();
        }
    }

    escapeHtml(text) {
        if (!text) return "";
        const map = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#039;",
        };
        return text.replace(/[&<>"']/g, (m) => map[m]);
    }
}

// Initialize chat when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
    // Get assessment data from template
    let assessment = {};
    if (typeof ASSESSMENT !== "undefined") {
        assessment = ASSESSMENT;
    }

    window.chat = new ChatSession(SCAN_ID, assessment);
});