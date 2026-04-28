from fastapi import APIRouter

from app.api.v1 import admin, annotations, assets, auth, brief, chat, derivation, exports, feedback, generation, notifications, organizations, presentation_3d, professional_deliverables, projects, reviews, share, uploads

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(assets.router)
router.include_router(organizations.router)
router.include_router(projects.router)
router.include_router(brief.router)
router.include_router(chat.router)
router.include_router(generation.router)
router.include_router(annotations.router)
router.include_router(reviews.router)
router.include_router(share.router)
router.include_router(feedback.router)
router.include_router(exports.router)
router.include_router(derivation.router)
router.include_router(presentation_3d.router)
router.include_router(professional_deliverables.router)
router.include_router(notifications.router)
router.include_router(uploads.router)
router.include_router(admin.router)
