import { useState, useRef, useEffect, useCallback } from 'react';
import { MessageCircle, Send, Sparkles, ShieldX } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { apiClient } from '@/mock/api';
import { INVARIANT } from '@/mock/data';
import type { ChatMessage, AskResponse } from '@/types';
import { AnswerCard } from '@/components/AnswerCard';
import { TrustPanel } from '@/components/TrustPanel';
import { ConfirmationCard } from '@/components/ConfirmationCard';
import { StatusStepper } from '@/components/StatusStepper';
import { EmptyState } from '@/components/EmptyState';

const examplePrompts = [
  'What is total revenue?',
  'Revenue by region',
  'Trend of orders over time',
  'Describe the data',
];

let msgId = 0;
const nextId = () => `msg-${++msgId}`;

export function AskPage() {
  const { tenant, restoredQuestion, clearRestoredQuestion } = useApp();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingSteps, setLoadingSteps] = useState<
    { label: string; status: 'done' | 'active' | 'pending' }[]
  >([]);
  const [lastResponse, setLastResponse] = useState<AskResponse | null>(null);
  const [confirmationToken, setConfirmationToken] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const sendQuestionRef = useRef<(question: string) => Promise<void>>(async () => {});

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loadingSteps, scrollToBottom]);

  useEffect(() => {
    if (restoredQuestion) {
      sendQuestionRef.current(restoredQuestion);
      clearRestoredQuestion();
    }
  }, [restoredQuestion, clearRestoredQuestion]);

  const sendQuestion = async (question: string) => {
    if (!question.trim() || loading) return;

    const userMsg: ChatMessage = {
      id: nextId(),
      role: 'user',
      text: question,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    setLastResponse(null);

    const response = await apiClient.askWithStepper(question, (steps) => {
      setLoadingSteps(steps);
    });
    const assistantMsg: ChatMessage = {
      id: nextId(),
      role: 'assistant',
      text: response.answer || (response.status === 'awaiting_confirmation' ? 'Confirmation required' : ''),
      response,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, assistantMsg]);
    setLoading(false);
    setLoadingSteps([]);

    if (response.status === 'completed') {
      setLastResponse(response);
      setConfirmationToken(null);
    } else if (response.status === 'awaiting_confirmation') {
      setLastResponse(response);
      setConfirmationToken(response.confirmationToken ?? null);
    }
  };

  const handleApprove = async () => {
    const token = confirmationToken;
    if (!token) return;

    // Optimistic: show a loading state
    setLoading(true);
    const result = await apiClient.confirmAction(token, true);
    setLoading(false);

    if (result && result.status === 'approved') {
      // Show approved response — backend only returns status, not full answer
      const approvedResponse: AskResponse = {
        status: 'completed',
        answer: 'Action approved and executed. The requested metric was computed successfully.',
        confidence: 'medium',
        flags: [{ type: 'metric_pending', label: 'Metric was pending — approved for this session', severity: 'warning' }],
        lineage: lastResponse?.lineage ?? [],
        plan_type: lastResponse?.plan_type ?? 'single_metric',
        invariant: result.invariant ?? INVARIANT,
        caveat: lastResponse?.caveat,
      };
      setLastResponse(approvedResponse);
      setConfirmationToken(null);
      setMessages((prev) => {
        const updated = [...prev];
        const lastAssistant = updated[updated.length - 1];
        if (lastAssistant && lastAssistant.role === 'assistant') {
          updated[updated.length - 1] = {
            ...lastAssistant,
            text: approvedResponse.answer,
            response: approvedResponse,
          };
        }
        return updated;
      });
    } else {
      // Error or null result
      const errorResponse: AskResponse = {
        status: 'error',
        answer: 'Failed to approve — the confirmation may have expired or the backend is unavailable.',
        confidence: 'low',
        flags: [{ type: 'unknown_metric', label: 'Confirmation failed', severity: 'critical' }],
        lineage: [],
        plan_type: 'single_metric',
        invariant: INVARIANT,
      };
      setLastResponse(errorResponse);
    }
  };

  const handleReject = async () => {
    const token = confirmationToken;
    if (!token) return;

    setLoading(true);
    const result = await apiClient.confirmAction(token, false);
    setLoading(false);

    const deniedResponse: AskResponse = {
      status: 'denied',
      answer: '',
      confidence: 'low',
      flags: [{ type: 'unknown_metric', label: 'Request rejected by user', severity: 'warning' }],
      lineage: [],
      plan_type: 'confirmation_required',
      invariant: result?.invariant ?? INVARIANT,
      deniedReason: 'Request rejected by user. No data was accessed.',
    };

    setLastResponse(null);
    setConfirmationToken(null);
    setMessages((prev) => {
      const updated = [...prev];
      const lastAssistant = updated[updated.length - 1];
      if (lastAssistant && lastAssistant.role === 'assistant') {
        updated[updated.length - 1] = {
          ...lastAssistant,
          text: 'Request denied',
          response: deniedResponse,
        };
      }
      return updated;
    });
  };

  useEffect(() => {
    sendQuestionRef.current = sendQuestion;
  });

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendQuestion(input);
    }
  };

  const isEmpty = messages.length === 0 && !loading;

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">
        {/* Conversation column */}
        <div className="flex-1 flex flex-col min-w-0">
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 sm:px-6 py-6">
            <div className="max-w-3xl mx-auto">
              {isEmpty ? (
                <EmptyState
                  icon={MessageCircle}
                  title="Ask a question"
                  description={`Ask anything about your business data in plain English. Every answer includes confidence, lineage, and safety flags. You're in ${tenant.name}.`}
                />
              ) : (
                <div className="space-y-4">
                  {messages.map((msg) => (
                    <div key={msg.id}>
                      {msg.role === 'user' ? (
                        <div className="flex justify-end animate-slide-up">
                          <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-brand-600 text-white px-4 py-2.5 text-sm shadow-sm">
                            {msg.text}
                          </div>
                        </div>
                      ) : (
                        <div className="animate-slide-up">
                          {msg.response?.status === 'denied' || msg.response?.status === 'error' ? (
                            <div className="rounded-xl border-2 border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/30 p-5">
                              <div className="flex items-center gap-2 mb-2">
                                <ShieldX className="h-5 w-5 text-red-600 dark:text-red-400" />
                                <h3 className="text-sm font-semibold text-red-900 dark:text-red-200">Request denied</h3>
                              </div>
                              <p className="text-sm text-red-800 dark:text-red-300">
                                {msg.response.deniedReason}
                              </p>
                            </div>
                          ) : msg.response?.status === 'awaiting_confirmation' ? (
                            <ConfirmationCard
                              response={msg.response}
                              onApprove={handleApprove}
                              onReject={handleReject}
                            />
                          ) : msg.response ? (
                            <AnswerCard
                              response={msg.response}
                              onWhy={() => {
                                setLastResponse(msg.response!);
                                document.getElementById('trust-panel')?.scrollIntoView({ behavior: 'smooth' });
                              }}
                            />
                          ) : null}
                        </div>
                      )}
                    </div>
                  ))}

                  {loading && (
                    <div className="max-w-md">
                      <StatusStepper steps={loadingSteps} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Composer */}
          <div className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 sm:px-6 py-4">
            <div className="max-w-3xl mx-auto">
              {isEmpty && (
                <div className="flex flex-wrap gap-2 mb-3">
                  {examplePrompts.map((prompt) => (
                    <button
                      key={prompt}
                      onClick={() => sendQuestion(prompt)}
                      className="badge-base bg-brand-50 text-brand-700 border border-brand-200 dark:bg-brand-950/50 dark:text-brand-300 dark:border-brand-800 hover:bg-brand-100 dark:hover:bg-brand-900/50 transition-all cursor-pointer animate-fade-in"
                    >
                      <Sparkles className="h-3 w-3" />
                      {prompt}
                    </button>
                  ))}
                </div>
              )}

              <div className="relative flex items-end gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 p-2 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/20 transition-all">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="What is total revenue by region?"
                  rows={1}
                  className="flex-1 resize-none bg-transparent text-sm outline-none px-2 py-1.5 max-h-32 text-slate-800 dark:text-slate-200 placeholder:text-slate-400"
                  style={{ minHeight: '36px' }}
                />
                <button
                  onClick={() => sendQuestion(input)}
                  disabled={!input.trim() || loading}
                  className="btn-primary p-2"
                  title="Send"
                >
                  <Send className="h-4 w-4" />
                </button>
              </div>
              <p className="text-xs text-slate-400 mt-2 text-center">
                The model selects from approved metrics — it never generates or executes SQL
              </p>
            </div>
          </div>
        </div>

        {/* Trust panel — right column / stacked below on mobile */}
        {lastResponse && (
          <div id="trust-panel" className="lg:w-80 xl:w-96 border-t lg:border-t-0 lg:border-l border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/50 p-4 overflow-y-auto">
            <TrustPanel response={lastResponse} />
          </div>
        )}
      </div>
    </div>
  );
}
