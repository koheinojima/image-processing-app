'use client';

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Play, Settings, Terminal, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import clsx from 'clsx';

export default function Home() {
  const [config, setConfig] = useState({
    project_name: "",
    input_photo_folder_id: "",
    input_logo_folder_id: "",
    output_root_folder_id: "",
    spreadsheet_id: "",
    photo_width: 900,
    photo_height: 600,
    force_contain_mode: false,
    processing_mode: "both" // both, photos, logos
  });

  const [status, setStatus] = useState('idle'); // idle, running, completed, error, stopped
  const [logs, setLogs] = useState<string[]>([]);
  const [lastLog, setLastLog] = useState("");
  const [resultLinks, setResultLinks] = useState<{ drive_folder: string, spreadsheet: string } | null>(null);
  const [progress, setProgress] = useState<{ processed: number, total: number } | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loadingAuth, setLoadingAuth] = useState(true);

  const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

  // Check auth on mount
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('authenticated') === 'true') {
          setIsAuthenticated(true);
          setLoadingAuth(false);
          // Clean up URL
          window.history.replaceState({}, document.title, window.location.pathname);
          return;
        }

        const res = await axios.get(`${baseUrl}/api/auth/check`, {
          withCredentials: true,
          timeout: 60000 // Increase to 60 seconds for Render cold start
        });
        setIsAuthenticated(res.data.authenticated);
      } catch (e) {
        console.error("Auth check failed", e);
        setIsAuthenticated(false);
      } finally {
        setLoadingAuth(false);
      }
    };
    checkAuth();
  }, []);

  const [isLoggingIn, setIsLoggingIn] = useState(false);

  const handleLogin = async () => {
    setIsLoggingIn(true);
    try {
      const res = await axios.get(`${baseUrl}/api/auth/login`, {
        timeout: 60000,
        withCredentials: true
      });
      if (res.data.url) {
        window.location.href = res.data.url;
      } else {
        alert("Login URL could not be retrieved: " + (res.data.error || "Unknown server error"));
        setIsLoggingIn(false);
      }
    } catch (e) {
      console.error("Login failed", e);
      alert(`Login request failed.\nTarget: ${baseUrl}\nError: ${String(e)}\n\nAPIのURLが "https://" で始まっているか、Vercelの環境変数が正しいか確認してください。`);
      setIsLoggingIn(false);
    }
  };

  // Load config from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem('image_proc_config');
    if (saved) {
      try {
        setConfig(prev => ({ ...prev, ...JSON.parse(saved) }));
      } catch (e) {
        console.error("Failed to load config", e);
      }
    }
  }, []);

  // Save config to localStorage whenever it changes
  useEffect(() => {
    localStorage.setItem('image_proc_config', JSON.stringify(config));
  }, [config]);

  useEffect(() => {
    let interval: NodeJS.Timeout;

    // Always poll if running, or if we just completed but missed links (safety net), or if stopping
    if (status === 'running' || (status === 'completed' && !resultLinks) || status === 'stopping') {
      interval = setInterval(async () => {
        try {
          const res = await axios.get(`${baseUrl}/api/status`, { withCredentials: true });

          if (res.data.logs) {
            setLogs(res.data.logs);
            if (res.data.logs.length > 0) {
              setLastLog(res.data.logs[res.data.logs.length - 1]);
            }
          }

          if (res.data.progress) {
            setProgress(res.data.progress);
          }

          // Result links checked separately to ensure they are captured
          if (res.data.result_links) {
            setResultLinks(res.data.result_links);
          }

          if (res.data.status === 'completed') {
            setStatus('completed');
            if (res.data.result_links) clearInterval(interval);
          }

          if (res.data.status === 'error') {
            setStatus('error');
            clearInterval(interval);
          }

          if (res.data.status === 'stopped') {
            setStatus('stopped');
            clearInterval(interval);
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [status, resultLinks]);

  const startProcess = async () => {
    try {
      setStatus('running');
      setLogs([]);
      setResultLinks(null);
      setProgress(null);
      await axios.post(`${baseUrl}/api/start`, config, { withCredentials: true });
    } catch (e) {
      console.error(e);
      setStatus('error');
      setLogs(prev => [...prev, "処理の開始に失敗しました: " + String(e)]);
    }
  };

  const stopProcess = async () => {
    try {
      await axios.post(`${baseUrl}/api/stop`, {}, { withCredentials: true });
      setLogs(prev => [...prev, "中断リクエストを送信しました..."]);
    } catch (e) {
      console.error("Stop error", e);
    }
  };

  if (loadingAuth) {
    return <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
      <Loader2 className="animate-spin w-10 h-10 text-indigo-500" />
    </div>;
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center p-8">
        <div className="max-w-md w-full bg-slate-800 p-8 rounded-2xl border border-slate-700 shadow-2xl text-center">
          <h1 className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-purple-400 mb-6">
            Image Processor Login
          </h1>
          <p className="text-slate-400 mb-8">
            Googleアカウントでログインして、画像処理を開始してください。<br />
            (Google Drive & Sheetsへのアクセス権限が必要です)
          </p>
          <button
            onClick={handleLogin}
            className="w-full py-4 bg-white text-slate-900 rounded-xl font-bold text-lg hover:bg-slate-100 transition-all flex items-center justify-center gap-3"
          >
            <svg className="w-6 h-6" viewBox="0 0 24 24">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
              <path d="M5.84 14.13c-.22-.66-.35-1.36-.35-2.13s.13-1.47.35-2.13V7.03H2.18C1.52 8.35 1.14 9.8 1.14 12c0 2.2.38 3.65 1.05 4.97l3.65-2.84z" fill="#FBBC05" />
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.03l3.65 2.84c.87-2.6 3.3-4.49 6.16-4.49z" fill="#EA4335" />
            </svg>
            Googleでログイン
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-8 font-sans selection:bg-indigo-500 selection:text-white">
      <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-8">

        {/* Left Column: Configuration */}
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-slate-800/50 backdrop-blur-sm p-6 rounded-2xl border border-slate-700 shadow-xl">
            <h2 className="flex items-center gap-2 text-xl font-bold text-indigo-400 mb-6">
              <Settings className="w-5 h-5" /> 設定 (Configuration)
            </h2>

            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-bold text-slate-400 uppercase tracking-wider">処理モード (Processing Mode)</label>
                <div className="flex bg-slate-700/50 p-1 rounded-xl gap-1">
                  {[
                    { id: 'both', label: '両方', desc: 'Both' },
                    { id: 'photos', label: '写真', desc: 'Photos' },
                    { id: 'logos', label: 'ロゴ', desc: 'Logos' }
                  ].map((m) => (
                    <button
                      key={m.id}
                      onClick={() => setConfig({ ...config, processing_mode: m.id })}
                      className={clsx(
                        "flex-1 py-2 rounded-lg text-sm font-bold transition-all",
                        config.processing_mode === m.id
                          ? "bg-indigo-500 text-white shadow-lg"
                          : "text-slate-400 hover:text-slate-200 hover:bg-slate-700"
                      )}
                    >
                      {m.label} <span className="text-[10px] opacity-60 ml-0.5">{m.desc}</span>
                    </button>
                  ))}
                </div>
              </div>

              <InputGroup label="プロジェクト名" placeholder="例: 2024_Spring_Campaign" value={config.project_name} onChange={v => setConfig({ ...config, project_name: v })} />
              <InputGroup label="写真フォルダID" placeholder="Google Drive Folder ID" value={config.input_photo_folder_id} onChange={v => setConfig({ ...config, input_photo_folder_id: v })} />
              <InputGroup label="ロゴフォルダID" placeholder="(任意) Google Drive Folder ID" value={config.input_logo_folder_id} onChange={v => setConfig({ ...config, input_logo_folder_id: v })} />
              <InputGroup label="出力先ルートフォルダID" placeholder="Google Drive Folder ID" value={config.output_root_folder_id} onChange={v => setConfig({ ...config, output_root_folder_id: v })} />
              <InputGroup label="スプレッドシートID" placeholder="(任意) Google Sheets ID" value={config.spreadsheet_id} onChange={v => setConfig({ ...config, spreadsheet_id: v })} />

              <div className="grid grid-cols-2 gap-4">
                <InputGroup label="幅 (Width)" type="number" placeholder="900" value={config.photo_width} onChange={v => setConfig({ ...config, photo_width: Number(v) })} />
                <InputGroup label="高さ (Height)" type="number" placeholder="600" value={config.photo_height} onChange={v => setConfig({ ...config, photo_height: Number(v) })} />
              </div>

              <div className="flex items-center gap-3 pt-2">
                <input
                  type="checkbox"
                  id="force_contain"
                  checked={config.force_contain_mode}
                  onChange={e => setConfig({ ...config, force_contain_mode: e.target.checked })}
                  className="w-5 h-5 rounded border-slate-600 text-indigo-500 focus:ring-indigo-500 bg-slate-700"
                />
                <label htmlFor="force_contain" className="text-sm font-medium text-slate-300 cursor-pointer">
                  強制全体表示モード (クロップなし)
                </label>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={startProcess}
              disabled={status === 'running'}
              className={clsx(
                "py-4 rounded-xl font-bold text-lg shadow-lg transition-all duration-300 flex items-center justify-center gap-2 col-span-2 md:col-span-1",
                status === 'running'
                  ? "bg-slate-700 text-slate-400 cursor-not-allowed"
                  : "bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 text-white hover:shadow-indigo-500/25"
              )}
            >
              {status === 'running' ? <Loader2 className="animate-spin" /> : <Play fill="currentColor" />}
              {status === 'running' ? '処理中' : '開始'}
            </button>

            <button
              onClick={stopProcess}
              disabled={status !== 'running'}
              className={clsx(
                "py-4 rounded-xl font-bold text-lg shadow-lg transition-all duration-300 flex items-center justify-center gap-2 col-span-2 md:col-span-1",
                status !== 'running'
                  ? "bg-slate-800 text-slate-600 cursor-not-allowed border border-slate-700"
                  : "bg-rose-500/20 text-rose-400 border border-rose-500/50 hover:bg-rose-500/30"
              )}
            >
              停止
            </button>
          </div>
        </div>

        {/* Right Column: Logs & Status */}
        <div className="lg:col-span-2 space-y-6">
          {/* Status Card */}
          <div className="grid grid-cols-2 gap-4">
            <StatusCard title="ステータス" value={status === 'idle' ? '待機中' : status === 'running' ? '実行中' : status === 'completed' ? '完了' : status === 'stopped' ? '中断' : 'エラー'} icon={
              status === 'completed' ? <CheckCircle className="text-emerald-400" /> :
                status === 'error' ? <AlertCircle className="text-rose-400" /> :
                  status === 'stopped' ? <AlertCircle className="text-amber-400" /> :
                    <Terminal className="text-indigo-400" />
            } />
            <StatusCard title="進捗" value={progress ? `${progress.processed} / ${progress.total}` : "---"} />
          </div>

          {/* Progress Bar */}
          {status === 'running' && progress && progress.total > 0 && (
            <div className="bg-slate-800/50 p-4 rounded-2xl border border-slate-700">
              <div className="flex justify-between text-xs text-slate-400 mb-2 uppercase font-bold tracking-wider">
                <span>Progress</span>
                <span>{Math.round((progress.processed / progress.total) * 100)}%</span>
              </div>
              <div className="h-4 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-all duration-500 ease-out"
                  style={{ width: `${(progress.processed / progress.total) * 100}%` }}
                />
              </div>
            </div>
          )}

          {/* Success Result Card */}
          {(status === 'completed' || status === 'stopped') && resultLinks && (
            <div className="bg-emerald-500/10 border border-emerald-500/30 p-6 rounded-2xl animate-in fade-in slide-in-from-top-4">
              <h3 className="text-emerald-400 font-bold text-lg mb-3 flex items-center gap-2">
                <CheckCircle className="w-5 h-5" /> {status === 'completed' ? '処理が完了しました！' : '処理は中断されましたが、途中経過は保存されています'}
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <a href={resultLinks.drive_folder} target="_blank" rel="noopener noreferrer"
                  className="block p-4 bg-slate-800 rounded-xl border border-slate-700 hover:border-emerald-500 hover:bg-slate-700/80 transition-all group">
                  <div className="text-xs text-slate-400 font-bold uppercase mb-1">出力先フォルダ</div>
                  <div className="text-white font-medium truncate group-hover:text-emerald-400">Google Driveを開く &rarr;</div>
                </a>
                {resultLinks.spreadsheet && (
                  <a href={resultLinks.spreadsheet} target="_blank" rel="noopener noreferrer"
                    className="block p-4 bg-slate-800 rounded-xl border border-slate-700 hover:border-emerald-500 hover:bg-slate-700/80 transition-all group">
                    <div className="text-xs text-slate-400 font-bold uppercase mb-1">結果シート</div>
                    <div className="text-white font-medium truncate group-hover:text-emerald-400">スプレッドシートを開く &rarr;</div>
                  </a>
                )}
              </div>
            </div>
          )}

          {/* Terminal */}
          <div className="bg-[#0f172a] rounded-2xl border border-slate-700 shadow-2xl overflow-hidden flex flex-col h-[500px]">
            <div className="bg-slate-800 px-4 py-2 flex items-center gap-2 border-b border-slate-700">
              <div className="flex gap-1.5">
                <div className="w-3 h-3 rounded-full bg-rose-500/80" />
                <div className="w-3 h-3 rounded-full bg-amber-500/80" />
                <div className="w-3 h-3 rounded-full bg-emerald-500/80" />
              </div>
              <span className="text-xs font-mono text-slate-400 ml-2">実行ログ (Console Output)</span>
            </div>
            <div className="flex-1 p-4 font-mono text-sm overflow-y-auto space-y-1 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
              {logs.length === 0 && <span className="text-slate-600 italic">待機中...</span>}
              {logs.map((log, i) => (
                <div key={i} className="text-slate-300 border-l-2 border-slate-800 pl-2 hover:border-indigo-500 transition-colors">
                  <span className="text-slate-500 text-xs mr-2">[{new Date().toLocaleTimeString()}]</span>
                  {log}
                </div>
              ))}
              <div id="log-end" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function InputGroup({ label, value, onChange, type = "text", placeholder }: { label: string, value: string | number, onChange: (v: any) => void, type?: string, placeholder?: string }) {
  return (
    <div>
      <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">{label}</label>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
        className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition-all placeholder:text-slate-600"
      />
    </div>
  );
}

function StatusCard({ title, value, icon }: { title: string, value: string, icon?: React.ReactNode }) {
  return (
    <div className="bg-slate-800/80 p-5 rounded-xl border border-slate-700">
      <div className="text-slate-400 text-xs font-bold uppercase mb-1 flex items-center justify-between">
        {title}
        {icon}
      </div>
      <div className="text-xl font-medium text-white truncate" title={value}>{value}</div>
    </div>
  );
}
