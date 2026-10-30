'use client';

import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, KeyRound } from 'lucide-react';

interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: Date;
}

export default function Twin() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId, setSessionId] = useState<string>('');
    // Bring-your-own-key: the Groq key lives in React state only (this tab's memory).
    // It is never written to localStorage, cookies, URLs or logs.
    const [apiKey, setApiKey] = useState<string>('');
    const [keyInput, setKeyInput] = useState('');
    const [keyError, setKeyError] = useState('');
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const connectKey = (e: React.FormEvent) => {
        e.preventDefault();
        const key = keyInput.trim();
        if (!key.startsWith('gsk_')) {
            setKeyError("That doesn't look like a Groq API key (they start with gsk_).");
            return;
        }
        setApiKey(key);
        setKeyInput('');
        setKeyError('');
    };

    const forgetKey = () => {
        setApiKey('');
        setKeyInput('');
    };

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const sendMessage = async () => {
        if (!input.trim() || isLoading) return;

        const userMessage: Message = {
            id: Date.now().toString(),
            role: 'user',
            content: input,
            timestamp: new Date(),
        };

        setMessages(prev => [...prev, userMessage]);
        setInput('');
        setIsLoading(true);

        try {
            const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Groq-Api-Key': apiKey,
                },
                body: JSON.stringify({
                    message: input,
                    session_id: sessionId || undefined,
                }),
            });

            if (response.status === 401) {
                // Groq rejected the key: drop it and ask again
                forgetKey();
                setKeyError('Groq rejected that API key. Please connect a valid key.');
                setMessages(prev => prev.slice(0, -1));
                return;
            }
            if (response.status === 429) {
                throw new Error('rate_limit');
            }
            if (!response.ok) throw new Error('Failed to send message');

            const data = await response.json();

            if (!sessionId) {
                setSessionId(data.session_id);
            }

            const assistantMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: data.response,
                timestamp: new Date(),
            };

            setMessages(prev => [...prev, assistantMessage]);
        } catch (error) {
            console.error('Error:', error);
            // Add error message
            const errorMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content:
                    error instanceof Error && error.message === 'rate_limit'
                        ? 'Your free Groq key hit its per-minute limit. Wait about 30 seconds and try again.'
                        : 'Sorry, I encountered an error. Please try again.',
                timestamp: new Date(),
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleKeyPress = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    // Gate: no chat until the visitor connects their own Groq key
    if (!apiKey) {
        return (
            <div className="flex flex-col h-full bg-gray-50 rounded-lg shadow-lg">
                <div className="bg-gradient-to-r from-slate-700 to-slate-800 text-white p-4 rounded-t-lg">
                    <h2 className="text-xl font-semibold flex items-center gap-2">
                        <Bot className="w-6 h-6" />
                        AI Digital Twin
                    </h2>
                    <p className="text-sm text-slate-300 mt-1">Powered by Groq</p>
                </div>
                <form onSubmit={connectKey} className="flex-1 flex flex-col items-center justify-center gap-4 p-6 text-center">
                    <KeyRound className="w-10 h-10 text-gray-400" />
                    <p className="text-gray-700 font-medium">Connect your Groq API key to start chatting</p>
                    <p className="text-sm text-gray-500 max-w-md">
                        Get a free key at{' '}
                        <a className="underline" href="https://console.groq.com/keys" target="_blank" rel="noopener noreferrer">
                            console.groq.com/keys
                        </a>
                        . It stays in this browser tab only and is never stored.
                    </p>
                    <input
                        type="password"
                        value={keyInput}
                        onChange={(e) => setKeyInput(e.target.value)}
                        placeholder="gsk_..."
                        autoComplete="off"
                        className="w-full max-w-md px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-600 text-gray-800"
                    />
                    {keyError && <p className="text-sm text-red-600">{keyError}</p>}
                    <button
                        type="submit"
                        disabled={!keyInput.trim()}
                        className="px-6 py-2 bg-slate-700 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                        Connect
                    </button>
                </form>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full bg-gray-50 rounded-lg shadow-lg">
            {/* Header */}
            <div className="bg-gradient-to-r from-slate-700 to-slate-800 text-white p-4 rounded-t-lg">
                <div className="flex items-start justify-between gap-2">
                    <div>
                        <h2 className="text-xl font-semibold flex items-center gap-2">
                            <Bot className="w-6 h-6" />
                            AI Digital Twin
                        </h2>
                        <p className="text-sm text-slate-300 mt-1">Powered by Groq</p>
                    </div>
                    <button
                        onClick={forgetKey}
                        className="text-xs text-slate-300 hover:text-white underline"
                    >
                        Forget key
                    </button>
                </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.length === 0 && (
                    <div className="text-center text-gray-500 mt-8">
                        <Bot className="w-12 h-12 mx-auto mb-3 text-gray-400" />
                        <p>Hello! I&apos;m Arash&apos;s digital twin.</p>
                        <p className="text-sm mt-2">Ask me about my background, skills and projects.</p>
                    </div>
                )}

                {messages.map((message) => (
                    <div
                        key={message.id}
                        className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'
                            }`}
                    >
                        {message.role === 'assistant' && (
                            <div className="flex-shrink-0">
                                <div className="w-8 h-8 bg-slate-700 rounded-full flex items-center justify-center">
                                    <Bot className="w-5 h-5 text-white" />
                                </div>
                            </div>
                        )}

                        <div
                            className={`max-w-[70%] rounded-lg p-3 ${message.role === 'user'
                                ? 'bg-slate-700 text-white'
                                : 'bg-white border border-gray-200 text-gray-800'
                                }`}
                        >
                            <p className="whitespace-pre-wrap">{message.content}</p>
                            <p
                                className={`text-xs mt-1 ${message.role === 'user' ? 'text-slate-300' : 'text-gray-500'
                                    }`}
                            >
                                {message.timestamp.toLocaleTimeString()}
                            </p>
                        </div>

                        {message.role === 'user' && (
                            <div className="flex-shrink-0">
                                <div className="w-8 h-8 bg-gray-600 rounded-full flex items-center justify-center">
                                    <User className="w-5 h-5 text-white" />
                                </div>
                            </div>
                        )}
                    </div>
                ))}

                {isLoading && (
                    <div className="flex gap-3 justify-start">
                        <div className="flex-shrink-0">
                            <div className="w-8 h-8 bg-slate-700 rounded-full flex items-center justify-center">
                                <Bot className="w-5 h-5 text-white" />
                            </div>
                        </div>
                        <div className="bg-white border border-gray-200 rounded-lg p-3">
                            <div className="flex space-x-2">
                                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100" />
                                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200" />
                            </div>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="border-t border-gray-200 p-4 bg-white rounded-b-lg">
                <div className="flex gap-2">
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyPress}
                        placeholder="Type your message..."
                        className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-600 focus:border-transparent text-gray-800"
                        disabled={isLoading}
                    />
                    <button
                        onClick={sendMessage}
                        disabled={!input.trim() || isLoading}
                        className="px-4 py-2 bg-slate-700 text-white rounded-lg hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                        <Send className="w-5 h-5" />
                    </button>
                </div>
            </div>
        </div>
    );
}