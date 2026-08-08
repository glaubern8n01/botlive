import {defineConfig} from 'playwright/test';
export default defineConfig({testDir:'./tests',timeout:90000,retries:0,workers:1,use:{trace:'retain-on-failure',actionTimeout:3000},reporter:'line'});
