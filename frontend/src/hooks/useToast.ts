import { create } from 'zustand'

export interface Toast {
  id: string
  type: 'success' | 'error' | 'warning' | 'info'
  message: string
}

interface ToastState {
  toasts: Toast[]
  add: (t: Omit<Toast, 'id'>) => void
  remove: (id: string) => void
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  add: (t) => {
    const id = Math.random().toString(36).slice(2)
    set((s) => ({ toasts: [...s.toasts, { ...t, id }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), 4000)
  },
  remove: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}))

export function useToast() {
  const add = useToastStore((s) => s.add)
  return {
    success: (message: string) => add({ type: 'success', message }),
    error: (message: string) => add({ type: 'error', message }),
    warning: (message: string) => add({ type: 'warning', message }),
    info: (message: string) => add({ type: 'info', message }),
  }
}
