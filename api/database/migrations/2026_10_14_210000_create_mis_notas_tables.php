<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

/**
 * Tablas sincronizables. Los IDs son UUID generados por el cliente y las fechas
 * son milisegundos desde epoch (las define el cliente; el servidor no las reescribe).
 * `rev` es un contador global que crece con cada escritura y sirve de cursor de sync.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('sync_counters', function (Blueprint $table) {
            $table->foreignId('user_id')->primary()->constrained()->cascadeOnDelete();
            $table->unsignedBigInteger('rev')->default(0);
        });

        Schema::create('notebooks', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignId('user_id')->constrained()->cascadeOnDelete();
            $table->string('name');
            $table->integer('sort')->default(0);
            $table->unsignedBigInteger('created_at');
            $table->unsignedBigInteger('updated_at');
            $table->unsignedBigInteger('deleted_at')->nullable();
            $table->unsignedBigInteger('rev');
            $table->index(['user_id', 'rev']);
        });

        Schema::create('notes', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignId('user_id')->constrained()->cascadeOnDelete();
            // Sin FK: la libreta puede llegar después que la nota durante la sincronización.
            $table->uuid('notebook_id')->nullable();
            $table->string('title')->default('');
            $table->json('blocks');
            $table->json('tags');
            $table->unsignedBigInteger('created_at');
            $table->unsignedBigInteger('updated_at');
            $table->unsignedBigInteger('trashed_at')->nullable();
            $table->unsignedBigInteger('deleted_at')->nullable();
            $table->unsignedBigInteger('rev');
            $table->index(['user_id', 'rev']);
        });

        Schema::create('attachments', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignId('user_id')->constrained()->cascadeOnDelete();
            $table->uuid('note_id')->nullable();
            $table->string('path');
            $table->string('mime');
            $table->unsignedBigInteger('size');
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('attachments');
        Schema::dropIfExists('notes');
        Schema::dropIfExists('notebooks');
        Schema::dropIfExists('sync_counters');
    }
};
