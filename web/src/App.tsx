// src/App.tsx
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './contexts/AuthContext'
import { AppPopupProvider } from './contexts/AppPopupContext'
import HomePage from './pages/HomePage'
import AboutPage from './pages/about/AboutPage'
import LoginPage from './pages/auth/LoginPage'
import RegisterPage from './pages/auth/RegisterPage'
import ForgotPasswordPage from './pages/auth/ForgotPasswordPage'
import ResetPasswordPage from './pages/auth/ResetPasswordPage'
import LandlordDashboardPage from './pages/dashboard/LandlordDashboardPage'
import TenantDashboardPage from './pages/dashboard/TenantDashboardPage'
import SearchPage from './pages/SearchPage'
import LocationAnalyticsPage from './pages/LocationAnalyticsPage'
import ListingDetailPage from './pages/listings/ListingDetailPage'
import EnquiriesPage from './pages/enquiries/EnquiriesPage'
import ChatThreadPage from './pages/messages/ChatThreadPage'
import VerifyMePage from './pages/verify/VerifyMePage'
import ProfilePage from './pages/profile/ProfilePage'
import FavouritesPage from './pages/favourites/FavouritesPage'
import RentPage from './pages/rent/RentPage'
import RentalProgressPage from './pages/rental/RentalProgressPage'
import ContactLandlordPage from './pages/messages/ContactLandlordPage'
import LandlordEnquiriesPage from './pages/landlord/LandlordEnquiriesPage'
import LandlordVerificationPage from './pages/landlord/LandlordVerificationPage'
import PublicLandlordProfilePage from './pages/landlord/PublicLandlordProfilePage'
import PublicLandlordPropertiesPage from './pages/landlord/PublicLandlordPropertiesPage'
import PublicTenantProfilePage from './pages/tenants/PublicTenantProfilePage'
import TenantProfilePage from './pages/tenants/TenantProfilePage'
import BillingPage from './pages/billing/BillingPage'
import SubscriptionPaymentPage from './pages/billing/SubscriptionPaymentPage'
import ListingFormPage from './pages/listings/ListingFormPage'
import FeaturedPropertiesPage from './pages/dashboard/FeaturedPropertiesPage'
import FeaturedPropertyPaymentPage from './pages/dashboard/FeaturedPropertyPaymentPage'
import SettingsPage from './pages/settings/SettingsPage'
import FeedbackPage from './pages/feedback/FeedbackPage'
import HowItWorksPage from './pages/how-it-works/HowItWorksPage'
import LegalDocumentPage from './pages/legal/LegalDocumentPage'
import TenantComplaintPage from './pages/support/TenantComplaintPage'
import TenantIssuesPage from './pages/support/TenantIssuesPage'
import TenantSupportPage from './pages/support/TenantSupportPage'
import SupportChatPage from './pages/support/SupportChatPage'
import CommunityChatPage from './pages/support/CommunityChatPage'
import AdminVerificationPage from './pages/admin/AdminVerificationPage'
import AdminLoginPage from './pages/admin/AdminLoginPage'
import AdminDashboardPage from './pages/admin/AdminDashboardPage'
import AdminRegisterPage from './pages/admin/AdminRegisterPage'
import AdminRouteWrapper from './components/AdminRouteWrapper'
import ProtectedRoute from './components/ProtectedRoute'

const queryClient = new QueryClient()

function App()
{
    return (
        <QueryClientProvider client={queryClient}>
            <Router>
                <AuthProvider>
                    <AppPopupProvider>
                        <AdminRouteWrapper>
                            <Routes>
                            {/* Public Routes */}
<Route path="/" element={<HomePage />} />
                            <Route path="/about" element={<AboutPage />} />
                            <Route path="/how-it-works" element={<HowItWorksPage />} />
                            <Route path="/legal/:slug" element={<LegalDocumentPage />} />
                            <Route path="/login" element={<LoginPage />} />
                            <Route path="/register" element={<RegisterPage />} />
                            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                            <Route path="/reset-password/:token" element={<ResetPasswordPage />} />
                            <Route path="/dashboard/landlord/:userId" element={<LandlordDashboardPage />} />
                            <Route path="/dashboard/tenant/:userId" element={<TenantDashboardPage />} />
                            <Route path="/search" element={<SearchPage />} />
                            <Route path="/search/location-analytics" element={<LocationAnalyticsPage />} />
                            <Route path="/listings/new" element={
                                <ProtectedRoute requiredRoles={['landlord', 'admin']}>
                                    <ListingFormPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/listings/:id/edit" element={
                                <ProtectedRoute requiredRoles={['landlord', 'admin']}>
                                    <ListingFormPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/listings/:id" element={<ListingDetailPage />} />
                            <Route path="/enquiries" element={<EnquiriesPage />} />
                            <Route path="/chat/:userId" element={<ChatThreadPage />} />
                            <Route path="/verify" element={<VerifyMePage />} />
                            <Route path="/profile/:userId" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord', 'admin']}>
                                    <ProfilePage />
                                </ProtectedRoute>
                            } />
                            <Route path="/tenants/:tenantId/profile" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord', 'admin']}>
                                    <TenantProfilePage />
                                </ProtectedRoute>
                            } />
                            <Route path="/tenants/:tenantId" element={<PublicTenantProfilePage />} />
                            <Route path="/billing" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                    <BillingPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/billing/subscriptions/pay/:paymentId" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                    <SubscriptionPaymentPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/dashboard/settings" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord', 'admin']}>
                                    <SettingsPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/feedback" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                    <FeedbackPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/complaint" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                    <TenantComplaintPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/issues" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                    <TenantIssuesPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/support" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                    <TenantSupportPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/support-chat" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                    <SupportChatPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/community-chat" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                    <CommunityChatPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/favourites" element={<FavouritesPage />} />
                            <Route path="/rent/:id" element={<RentPage />} />
                            <Route path="/rental-progress/:bookingId" element={
                                <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                    <RentalProgressPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/contact-landlord/:id" element={<ContactLandlordPage />} />
                            <Route path="/landlord/enquiries" element={<LandlordEnquiriesPage />} />
                            <Route path="/landlord/verification" element={
                                <ProtectedRoute requiredRoles={['landlord']}>
                                    <LandlordVerificationPage />
                                </ProtectedRoute>
                            } />
                            <Route path="/landlords/:landlordId/properties" element={<PublicLandlordPropertiesPage />} />
                            <Route path="/landlords/:landlordId" element={<PublicLandlordProfilePage />} />
                            <Route path="/dashboard/featured-properties" element={<FeaturedPropertiesPage />} />
                            <Route path="/dashboard/featured-properties/pay/:paymentId" element={<FeaturedPropertyPaymentPage />} />

                            {/* Admin Routes - No Public Navbar */}
                            <Route path="/admin/login" element={<AdminLoginPage />} />
                            <Route path="/admin/register" element={<AdminRegisterPage />} />
                            <Route path="/admin/dashboard" element={<AdminDashboardPage />} />
                            <Route path="/admin/verification" element={<AdminVerificationPage />} />
                            </Routes>
                        </AdminRouteWrapper>
                    </AppPopupProvider>
                </AuthProvider>
            </Router>
        </QueryClientProvider>
    )
}

export default App
