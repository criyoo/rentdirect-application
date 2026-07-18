/**
 * Format a number as NGN currency (Nigerian Naira)
 * Removes leading zeros and adds comma separators
 * @param amount - The amount to format (can be number or string)
 * @returns Formatted currency string without leading zeros, with comma separators
 */
export const formatCurrency = (amount: number | string): string => {
  // Convert to number to strip any leading zeros or non-numeric characters
  const num = Number(amount)
  
  // Handle NaN or invalid numbers
  if (isNaN(num)) {
    return '₦0'
  }
  
  // Use toLocaleString for comma separators
  // This will properly format without leading zeros
  return num.toLocaleString()
}

/**
 * Format a number as NGN currency with the ₦ symbol
 * @param amount - The amount to format (can be number or string)
 * @returns Formatted currency string with ₦ symbol
 */
export const formatCurrencyWithSymbol = (amount: number | string): string => {
  return `₦${formatCurrency(amount)}`
}