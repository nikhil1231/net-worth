import { type ComponentProps, type ReactNode, createContext, useContext, useState } from 'react'
import { Tooltip } from 'recharts'

const ChartTooltipMode = createContext({ hover: false, pinned: true })

/**
 * One behavior for chart tooltips: click to select, leave the chart to dismiss.
 * With `hover`, the tooltip follows the pointer and a click pins it, so links inside it can be reached.
 */
export function ChartFrame({ children, hover = false }: { children: ReactNode; hover?: boolean }) {
  const [pinned, setPinned] = useState(false)
  return <div onClick={() => setPinned(true)} onMouseLeave={() => setPinned(false)}>
    <ChartTooltipMode.Provider value={{ hover, pinned }}>{children}</ChartTooltipMode.Provider>
  </div>
}

export function ChartTooltip(props: ComponentProps<typeof Tooltip>) {
  const { hover, pinned } = useContext(ChartTooltipMode)
  if (hover) return <Tooltip {...props} trigger={pinned ? 'click' : 'hover'} />
  return <Tooltip {...props} trigger="click" active={pinned ? undefined : false} />
}
