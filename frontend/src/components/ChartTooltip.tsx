import { type ComponentProps, type ReactNode, createContext, useContext, useState } from 'react'
import { Tooltip } from 'recharts'

const ChartTooltipVisibility = createContext(true)

/** One behavior for chart tooltips: click to select, leave the chart to dismiss. */
export function ChartFrame({ children }: { children: ReactNode }) {
  const [visible, setVisible] = useState(false)
  return <div onClick={() => setVisible(true)} onMouseLeave={() => setVisible(false)}>
    <ChartTooltipVisibility.Provider value={visible}>{children}</ChartTooltipVisibility.Provider>
  </div>
}

export function ChartTooltip(props: ComponentProps<typeof Tooltip>) {
  const visible = useContext(ChartTooltipVisibility)
  return <Tooltip {...props} trigger="click" active={visible ? undefined : false} />
}
