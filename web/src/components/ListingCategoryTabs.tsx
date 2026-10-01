type ListingCategoryTab = 'residential' | 'commercial' | 'shortlet'

const categories: Array<{ value: ListingCategoryTab; label: string }> = [
    { value: 'residential', label: 'Residential' },
    { value: 'commercial', label: 'Commercial' },
    { value: 'shortlet', label: 'Shortlet' },
]

interface ListingCategoryTabsProps {
    value: ListingCategoryTab
    onChange: (value: ListingCategoryTab) => void
    className?: string
}

export default function ListingCategoryTabs({ value, onChange, className = '' }: ListingCategoryTabsProps) {
    return (
        <div
            role="tablist"
            aria-label="Property category"
            className={`inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white p-1 shadow-sm ${className}`}
        >
            {categories.map((category) => {
                const isActive = value === category.value
                return (
                    <button
                        key={category.value}
                        type="button"
                        role="tab"
                        aria-selected={isActive}
                        onClick={() => onChange(category.value)}
                        className={`rounded-full px-4 py-1.5 text-sm font-semibold transition ${
                            isActive
                                ? 'bg-blue-900 text-white shadow'
                                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                        }`}
                    >
                        {category.label}
                    </button>
                )
            })}
        </div>
    )
}
