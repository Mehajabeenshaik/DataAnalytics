export function EnvBadge({ env }: { env: 'Development' | 'Production' }) {
  const isDev = env === 'Development';
  return (
    <span
      className={`badge-base border ${
        isDev
          ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/50 dark:text-blue-400 dark:border-blue-800'
          : 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/50 dark:text-purple-400 dark:border-purple-800'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${isDev ? 'bg-blue-500' : 'bg-purple-500'} animate-pulse-soft`} />
      {env}
    </span>
  );
}
