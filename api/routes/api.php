<?php

use App\Http\Controllers\Api\AttachmentController;
use App\Http\Controllers\Api\SyncController;
use Illuminate\Support\Facades\Route;

Route::middleware('auth:sanctum')->group(function () {
    Route::get('/sync', [SyncController::class, 'pull']);
    Route::post('/sync', [SyncController::class, 'push']);
    Route::post('/attachments', [AttachmentController::class, 'store']);
    Route::get('/attachments/{id}', [AttachmentController::class, 'show'])->whereUuid('id');
});
