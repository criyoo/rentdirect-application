import { Fragment, ReactNode } from 'react'
import { Link } from 'react-router-dom'

type MarkdownBlock =
    | { type: 'heading'; level: 1 | 2 | 3 | 4; text: string }
    | { type: 'paragraph'; text: string }
    | { type: 'list'; ordered: boolean; items: string[] }
    | { type: 'quote'; text: string }
    | { type: 'table'; rows: string[][] }
    | { type: 'rule' }

function renderInlineMarkdown(text: string): ReactNode[] {
    const tokens = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g).filter(Boolean)

    return tokens.map((part, index) => {
        const key = `${part}-${index}`
        if (part.startsWith('**') && part.endsWith('**')) {
            return <strong key={key} className="font-semibold text-slate-900">{part.slice(2, -2)}</strong>
        }
        if (part.startsWith('`') && part.endsWith('`')) {
            return <code key={key} className="rounded bg-slate-100 px-1.5 py-0.5 text-[0.9em] text-slate-800">{part.slice(1, -1)}</code>
        }
        const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
        if (linkMatch) {
            const [, label, href] = linkMatch
            if (href.startsWith('/')) {
                return <Link key={key} to={href} className="font-medium text-blue-700 underline decoration-blue-200 underline-offset-2 hover:text-blue-900">{label}</Link>
            }
            return <a key={key} href={href} target="_blank" rel="noreferrer" className="font-medium text-blue-700 underline decoration-blue-200 underline-offset-2 hover:text-blue-900">{label}</a>
        }
        return <Fragment key={key}>{part}</Fragment>
    })
}

function parseMarkdown(markdown: string): MarkdownBlock[] {
    const blocks: MarkdownBlock[] = []
    const lines = markdown.replace(/\r/g, '').split('\n')
    let paragraphLines: string[] = []
    let listItems: string[] = []
    let listOrdered = false
    let quoteLines: string[] = []
    let tableRows: string[][] = []

    const flushParagraph = () => {
        const text = paragraphLines.join(' ').trim()
        if (text) blocks.push({ type: 'paragraph', text })
        paragraphLines = []
    }

    const flushList = () => {
        if (listItems.length > 0) blocks.push({ type: 'list', ordered: listOrdered, items: listItems })
        listItems = []
        listOrdered = false
    }

    const flushQuote = () => {
        const text = quoteLines.join(' ').trim()
        if (text) blocks.push({ type: 'quote', text })
        quoteLines = []
    }

    const flushTable = () => {
        if (tableRows.length > 0) blocks.push({ type: 'table', rows: tableRows })
        tableRows = []
    }

    for (const rawLine of lines) {
        const line = rawLine.trim()
        if (!line) {
            flushParagraph()
            flushList()
            flushQuote()
            flushTable()
            continue
        }

        if (/^---+$/.test(line)) {
            flushParagraph()
            flushList()
            flushQuote()
            flushTable()
            blocks.push({ type: 'rule' })
            continue
        }

        const headingMatch = line.match(/^(#{1,4})\s+(.*)$/)
        if (headingMatch) {
            flushParagraph()
            flushList()
            flushQuote()
            flushTable()
            blocks.push({ type: 'heading', level: headingMatch[1].length as 1 | 2 | 3 | 4, text: headingMatch[2].trim() })
            continue
        }

        if (line.startsWith('|') && line.endsWith('|')) {
            flushParagraph()
            flushList()
            flushQuote()
            const cells = line.slice(1, -1).split('|').map((cell) => cell.trim())
            if (!cells.every((cell) => /^:?-{3,}:?$/.test(cell))) tableRows.push(cells)
            continue
        }

        const quoteMatch = line.match(/^>\s?(.*)$/)
        if (quoteMatch) {
            flushParagraph()
            flushList()
            flushTable()
            quoteLines.push(quoteMatch[1].trim())
            continue
        }

        const listMatch = line.match(/^([-*])\s+(.*)$/) || line.match(/^\d+[.)]\s+(.*)$/)
        if (listMatch) {
            flushParagraph()
            flushQuote()
            flushTable()
            const ordered = /^\d/.test(line)
            if (listItems.length > 0 && ordered !== listOrdered) flushList()
            listOrdered = ordered
            listItems.push((ordered ? listMatch[1] : listMatch[2]).trim())
            continue
        }

        flushList()
        flushQuote()
        flushTable()
        paragraphLines.push(line)
    }

    flushParagraph()
    flushList()
    flushQuote()
    flushTable()
    return blocks
}

export default function LegalDocumentRenderer({ content }: { content: string }) {
    const blocks = parseMarkdown(content)

    return (
        <div className="space-y-3">
            {blocks.map((block, index) => {
                if (block.type === 'heading') {
                    const className = block.level === 1
                        ? 'border-b border-slate-200 pb-2 text-xl font-semibold leading-7 tracking-tight text-slate-950 md:text-2xl'
                        : block.level === 2
                            ? 'text-lg font-semibold leading-6 tracking-tight text-slate-950 md:text-xl'
                            : block.level === 3
                                ? 'text-base font-semibold leading-6 text-blue-800 md:text-lg'
                                : 'text-sm font-semibold leading-5 text-blue-800 md:text-base'
                    const Heading = block.level === 1 ? 'h1' : block.level === 2 ? 'h2' : block.level === 3 ? 'h3' : 'h4'
                    return <Heading key={index} className={className}>{renderInlineMarkdown(block.text)}</Heading>
                }

                if (block.type === 'list') {
                    const List = block.ordered ? 'ol' : 'ul'
                    return (
                        <List key={index} className={`${block.ordered ? 'list-decimal' : 'list-disc'} space-y-3 rounded-2xl bg-slate-50 px-6 py-5 pl-10 text-base leading-7 text-slate-700 marker:text-blue-600`}>
                            {block.items.map((item, itemIndex) => <li key={`${index}-${itemIndex}`} className="pl-2">{renderInlineMarkdown(item)}</li>)}
                        </List>
                    )
                }

                if (block.type === 'quote') {
                    return <blockquote key={index} className="rounded-r-2xl border-l-4 border-blue-500 bg-blue-50/70 px-5 py-4 text-base leading-7 text-slate-700">{renderInlineMarkdown(block.text)}</blockquote>
                }

                if (block.type === 'table') {
                    return (
                        <div key={index} className="overflow-x-auto rounded-2xl border border-slate-200">
                            <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
                                    <tr>{block.rows[0]?.map((cell, cellIndex) => <th key={cellIndex} className="px-4 py-3 font-semibold">{renderInlineMarkdown(cell)}</th>)}</tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100 bg-white text-slate-700">
                                    {block.rows.slice(1).map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex} className="px-4 py-3 align-top">{renderInlineMarkdown(cell)}</td>)}</tr>)}
                                </tbody>
                            </table>
                        </div>
                    )
                }

                if (block.type === 'rule') return <hr key={index} className="border-slate-200" />

                return <p key={index} className="text-base leading-8 text-slate-700 md:text-lg">{renderInlineMarkdown(block.text)}</p>
            })}
        </div>
    )
}
