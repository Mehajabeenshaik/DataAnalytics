import { useState } from 'react';
import { Shield, Mail, Lock, ArrowRight, Building } from 'lucide-react';
import { useApp } from '@/context/AppContext';

export function LoginPage() {
  const { login } = useApp();
  const [email, setEmail] = useState('admin@acme.co');
  const [password, setPassword] = useState('demo1234');
  const [loading, setLoading] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setTimeout(() => {
      login(email);
      setLoading(false);
    }, 600);
  };

  return (
    <div className="min-h-screen flex flex-col lg:flex-row bg-slate-50 dark:bg-slate-950">
      {/* Left panel — branding */}
      <div className="hidden lg:flex lg:w-1/2 bg-brand-900 dark:bg-brand-950 relative overflow-hidden">
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-20 left-20 w-72 h-72 rounded-full bg-brand-400 blur-3xl" />
          <div className="absolute bottom-20 right-20 w-96 h-96 rounded-full bg-brand-500 blur-3xl" />
        </div>
        <div className="relative z-10 flex flex-col justify-between p-12 text-white">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 backdrop-blur">
              <Shield className="h-6 w-6" />
            </div>
            <span className="text-2xl font-bold tracking-tight">DaAna</span>
          </div>

          <div className="max-w-md">
            <h1 className="text-4xl font-bold leading-tight mb-4">
              Governed AI analytics with trust built in.
            </h1>
            <br />

            <div className="mt-8 space-y-3">
              {[
                'Confidence-scored answers with full lineage',
                'Human-approved metrics — no ad-hoc SQL',
                'Audit trail with claimed vs. observed tools',
              ].map((item) => (
                <div key={item} className="flex items-center gap-3">
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-green-400/20">
                    <div className="h-2 w-2 rounded-full bg-green-400" />
                  </div>
                  <span className="text-sm text-brand-100">{item}</span>
                </div>
              ))}
            </div>
          </div>

          <p className="text-xs text-brand-300">
            Multi-tenant · Enterprise-grade · SOC 2 ready
          </p>
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <div className="lg:hidden flex items-center gap-3 mb-8">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white">
              <Shield className="h-6 w-6" />
            </div>
            <span className="text-2xl font-bold tracking-tight text-slate-800 dark:text-slate-200">DaAna</span>
          </div>

          <h2 className="text-2xl font-bold text-slate-800 dark:text-slate-200 mb-1">Sign in</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-8">
            Enter your credentials to access the analytics console.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                Email
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="input-base pl-10"
                  placeholder="you@company.com"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input-base pl-10"
                  placeholder="••••••••"
                  required
                />
              </div>
            </div>

            <button type="submit" disabled={loading} className="btn-primary w-full">
              {loading ? (
                <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <>
                  Sign in
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>

            <div className="relative py-2">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-slate-200 dark:border-slate-700" />
              </div>
              <div className="relative flex justify-center">
                <span className="bg-slate-50 dark:bg-slate-950 px-3 text-xs text-slate-400">or</span>
              </div>
            </div>

            <button type="button" className="btn-secondary w-full">
              <Building className="h-4 w-4" />
              Continue with SSO
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-slate-200 dark:border-slate-700">
            <p className="text-xs text-slate-400 text-center italic">
              Governed analytics — the model never executes SQL
            </p>
          </div>

          <div className="mt-4 rounded-lg bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-3">
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-1 font-medium">Demo accounts:</p>
            <p className="text-xs text-slate-400">admin@acme.co · analyst@demo.com</p>
          </div>
        </div>
      </div>
    </div>
  );
}
