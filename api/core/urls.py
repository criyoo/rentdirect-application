from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminViewSet,
    AuthViewSet,
    BookingViewSet,
    CommunityChatMessageViewSet,
    DashboardViewSet,
    DocumentViewSet,
    FeedbackViewSet,
    FavouriteViewSet,
    FeaturedViewSet,
    ListingViewSet,
    LandlordVerificationRequestViewSet,
    MessageViewSet,
    PaymentViewSet,
    ReviewViewSet,
    SubscriptionPaymentViewSet,
    SupportChatMessageViewSet,
    TenantVerificationRequestViewSet,
    UserViewSet,
    health,
    homepage_video,
)

router = DefaultRouter(trailing_slash=False)
router.register("auth", AuthViewSet, basename="auth")
router.register("users", UserViewSet, basename="users")
router.register("listings", ListingViewSet, basename="listings")
router.register("documents", DocumentViewSet, basename="documents")
router.register("landlord-verification-requests", LandlordVerificationRequestViewSet, basename="landlord-verification-requests")
router.register("tenant-verification-requests", TenantVerificationRequestViewSet, basename="tenant-verification-requests")
router.register("bookings", BookingViewSet, basename="bookings")
router.register("payments", PaymentViewSet, basename="payments")
router.register("subscriptions", SubscriptionPaymentViewSet, basename="subscriptions")
router.register("featured", FeaturedViewSet, basename="featured")
router.register("favourites", FavouriteViewSet, basename="favourites")
router.register("reviews", ReviewViewSet, basename="reviews")
router.register("feedback", FeedbackViewSet, basename="feedback")
router.register("messages", MessageViewSet, basename="messages")
router.register("community-chat/messages", CommunityChatMessageViewSet, basename="community-chat-messages")
router.register("support-chat/messages", SupportChatMessageViewSet, basename="support-chat-messages")
router.register("dashboard", DashboardViewSet, basename="dashboard")
router.register("admin", AdminViewSet, basename="admin")

subscription_payment_detail = SubscriptionPaymentViewSet.as_view({"get": "retrieve"})
subscription_payment_checkout = SubscriptionPaymentViewSet.as_view({"post": "flutterwave_checkout"})
featured_payment_detail = FeaturedViewSet.as_view({"get": "retrieve"})
featured_payment_checkout = FeaturedViewSet.as_view({"post": "flutterwave_checkout"})
featured_payment_update_duration = FeaturedViewSet.as_view({"put": "update_duration"})
featured_listing_unfeature = FeaturedViewSet.as_view({"delete": "unfeature"})

urlpatterns = [
    path("health", health),
    path("health/ready", health),
    path("v1/homepage-video", homepage_video),
    path("v1/subscriptions/payments/<uuid:pk>", subscription_payment_detail),
    path("v1/subscriptions/<uuid:pk>/flutterwave/checkout", subscription_payment_checkout),
    path("v1/featured/payments/<uuid:pk>", featured_payment_detail),
    path("v1/featured/payments/<uuid:pk>/update-duration", featured_payment_update_duration),
    path("v1/featured/<uuid:pk>/flutterwave/checkout", featured_payment_checkout),
    path("v1/featured/<uuid:pk>/unfeature", featured_listing_unfeature),
    path("v1/", include(router.urls)),
]
