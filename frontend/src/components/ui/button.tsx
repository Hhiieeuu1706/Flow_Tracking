import * as React from 'react'

import { cn } from '../../lib/cn'

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'secondary' | 'ghost' | 'destructive'
  size?: 'default' | 'sm' | 'icon'
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'default', ...props }, ref) => {
    const variantClass =
      variant === 'secondary'
        ? 'bg-zinc-800 text-zinc-50 hover:bg-zinc-700'
        : variant === 'ghost'
          ? 'bg-transparent text-zinc-200 hover:bg-zinc-900/60'
          : variant === 'destructive'
            ? 'bg-red-600 text-white hover:bg-red-500'
            : 'bg-violet-600 text-white hover:bg-violet-500'

    const sizeClass =
      size === 'sm'
        ? 'h-8 px-3 text-sm'
        : size === 'icon'
          ? 'h-9 w-9 p-0'
          : 'h-9 px-4 text-sm'

    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 disabled:pointer-events-none disabled:opacity-50',
          variantClass,
          sizeClass,
          className,
        )}
        {...props}
      />
    )
  },
)
Button.displayName = 'Button'

